"""CLI-based container image assembler adapter supporting Docker and Podman.

Notes/Architectural Intent:
    Implements ContainerImageAssemblerPort using local Docker or Podman CLI.
    Generates deterministic Containerfiles from ImageAssemblySpec, establishes
    isolated build contexts with injected binary/collateral artifacts, and
    verifies or updates local OCI image caches.
"""

import asyncio
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from hexaqueue_core.domain.container import ContainerRuntimeType
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_worker.domain.assembler import (
    AssembledImageResult,
    ImageAssemblySpec,
)
from hexaqueue_worker.ports.assembler import ContainerImageAssemblerPort


def _is_windows_spec(spec: ImageAssemblySpec) -> bool:
    """Determine whether the assembly target is a Windows container.

    Args:
        spec: ImageAssemblySpec instance.

    Returns:
        True if target is Windows, False otherwise.
    """
    wd = spec.workdir.lower()
    if wd.startswith("c:") or "\\" in wd:
        return True
    img = spec.base_image.lower()
    return "windows" in img or "servercore" in img or "nanoserver" in img


class CliContainerImageAssemblerAdapter(ContainerImageAssemblerPort):
    """Adapter executing dynamic container image builds via Docker or Podman CLI.

    Args:
        default_executable: Default CLI executable name ('docker' or 'podman').
        timeout_seconds: Maximum build duration before aborting.
    """

    def __init__(
        self,
        default_executable: str = "docker",
        timeout_seconds: int = 600,
    ) -> None:
        self._default_executable = default_executable
        self._timeout_seconds = timeout_seconds

    def _resolve_executable(self, runtime: ContainerRuntimeType | str | None) -> str:
        """Resolve container engine CLI executable string."""
        if not runtime:
            return self._default_executable
        return str(runtime).lower().strip()

    def generate_containerfile(
        self, spec: ImageAssemblySpec, build_context_dir: Path
    ) -> str:
        """Render Containerfile content string from assembly specification.

        Args:
            spec: ImageAssemblySpec definition.
            build_context_dir: Path to directory holding build artifacts.

        Returns:
            Rendered Dockerfile/Containerfile content.
        """
        lines: list[str] = [f"FROM {spec.base_image}"]
        is_win = _is_windows_spec(spec)

        if spec.workdir:
            lines.append(f"WORKDIR {spec.workdir}")

        for k, v in sorted(spec.env.items()):
            lines.append(f'ENV {k}="{v}"')

        for idx, art in enumerate(spec.artifacts):
            src = Path(art.source_path)
            rel_dest = f"artifacts/{idx}_{src.name}"
            dest_host = build_context_dir / rel_dest
            dest_host.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                if src.is_dir():
                    shutil.copytree(src, dest_host, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dest_host)
            lines.append(f"COPY {rel_dest} {art.target_path}")
            if art.executable and not is_win:
                lines.append(f"RUN chmod +x {art.target_path}")

        for cmd in spec.install_commands:
            lines.append(f"RUN {cmd}")

        return "\n".join(lines) + "\n"

    async def has_image(self, image_tag: str, runtime: str = "docker") -> bool:
        """Check if container image exists in local container engine image cache.

        Args:
            image_tag: Image tag or digest to inspect.
            runtime: Runtime CLI executable name ('docker' or 'podman').

        Returns:
            True if image exists, False otherwise.
        """
        exe = self._resolve_executable(runtime)
        cmd = [exe, "image", "inspect", image_tag]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception:
            return False

    async def remove_cached_image(
        self, image_tag: str, runtime: str = "docker"
    ) -> None:
        """Remove a cached container image from local storage.

        Args:
            image_tag: Image tag or digest to remove.
            runtime: Runtime CLI executable name ('docker' or 'podman').
        """
        exe = self._resolve_executable(runtime)
        cmd = [exe, "rmi", "-f", image_tag]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception:
            pass

    async def assemble_image(self, spec: ImageAssemblySpec) -> AssembledImageResult:
        """Assemble container image or serve from local cache if present.

        Args:
            spec: Assembly specification.

        Returns:
            AssembledImageResult detailing image tag and cache status.

        Raises:
            HexaqueueError: If container build fails.
        """
        start_time = datetime.now(UTC)
        tag = spec.image_tag
        runtime_exe = self._resolve_executable(spec.runtime)

        # 1. Check local container image cache
        if await self.has_image(tag, runtime=runtime_exe):
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            return AssembledImageResult(
                image_tag=tag,
                cached=True,
                build_time_seconds=elapsed,
            )

        # 2. Build image from ephemeral context
        with tempfile.TemporaryDirectory(prefix="hq-build-") as tmpdir:
            ctx_path = Path(tmpdir)
            dockerfile_content = self.generate_containerfile(spec, ctx_path)
            dockerfile_path = ctx_path / "Containerfile"
            dockerfile_path.write_text(dockerfile_content, encoding="utf-8")

            build_cmd = [
                runtime_exe,
                "build",
                "-t",
                tag,
                "-f",
                str(dockerfile_path),
                str(ctx_path),
            ]

            try:
                proc = await asyncio.create_subprocess_exec(
                    *build_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=float(self._timeout_seconds)
                )
            except TimeoutError as err:
                msg = f"Container image assembly timed out after {self._timeout_seconds}s for tag '{tag}'"
                raise HexaqueueError(msg) from err
            except Exception as err:
                msg = f"Failed to execute container build process: {err}"
                raise HexaqueueError(msg) from err

            output_text = (
                (stdout_bytes or b"").decode(errors="replace")
                + "\n"
                + (stderr_bytes or b"").decode(errors="replace")
            )

            if proc.returncode != 0:
                msg = (
                    f"Container image assembly failed for tag '{tag}' with exit code {proc.returncode}:\n"
                    f"{output_text.strip()}"
                )
                raise HexaqueueError(msg)

            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            return AssembledImageResult(
                image_tag=tag,
                cached=False,
                build_time_seconds=elapsed,
                log_output=output_text.strip(),
            )


__all__ = [
    "CliContainerImageAssemblerAdapter",
]
