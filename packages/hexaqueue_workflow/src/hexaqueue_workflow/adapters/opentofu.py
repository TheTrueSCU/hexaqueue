"""OpenTofu and Terraform infrastructure provisioning adapter.

Notes/Architectural Intent:
    Implements InfrastructureProvisionerPort by executing local OpenTofu or Terraform
    CLI subprocesses. Manages workspace preparation, tfvars generation, initialization,
    non-interactive auto-approved application, output extraction, and teardown.
"""

import asyncio
import contextlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hexaqueue_workflow.domain.exceptions import HexaqueueWorkflowError
from hexaqueue_workflow.domain.provisioner import (
    InfraPlanSpec,
    InfraProvisionResult,
)
from hexaqueue_workflow.ports.provisioner import InfrastructureProvisionerPort


class OpenTofuProvisionerAdapter(InfrastructureProvisionerPort):
    """Adapter executing infrastructure operations via OpenTofu or Terraform CLI.

    Args:
        executable_path: Name or filesystem path of the tofu/terraform CLI executable.
        default_timeout_seconds: Fallback execution timeout in seconds.
    """

    def __init__(
        self,
        executable_path: str = "tofu",
        default_timeout_seconds: int = 900,
    ) -> None:
        self._executable_path = executable_path
        self._default_timeout_seconds = default_timeout_seconds

    def _prepare_workspace(self, spec: InfraPlanSpec, workdir: Path) -> None:
        """Populate workspace directory with plan files and tfvars."""
        workdir.mkdir(parents=True, exist_ok=True)
        plan_src = Path(spec.plan_path)
        if plan_src.exists() and plan_src.is_dir() and plan_src != workdir:
            for item in plan_src.iterdir():
                dest = workdir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)

        if spec.variables:
            vars_file = workdir / "terraform.tfvars.json"
            vars_file.write_text(json.dumps(spec.variables, indent=2), encoding="utf-8")

    async def _run_command(
        self,
        args: list[str],
        workdir: Path,
        env: dict[str, str],
        timeout: int,
    ) -> tuple[int, str]:
        """Execute a CLI command within workspace and return exit code and combined output."""
        merged_env = {**os.environ, **env}
        cmd = [self._executable_path, f"-chdir={workdir}", *args]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=float(timeout)
            )
        except TimeoutError as err:
            proc.kill()
            msg = f"Command '{args[0]}' timed out after {timeout} seconds"
            raise HexaqueueWorkflowError(msg) from err

        combined = (
            (stdout or b"").decode(errors="replace")
            + "\n"
            + (stderr or b"").decode(errors="replace")
        )
        return proc.returncode or 0, combined.strip()

    async def provision(
        self, spec: InfraPlanSpec, workdir: Path
    ) -> InfraProvisionResult:
        """Initialize and apply infrastructure plan, returning extracted outputs."""
        start_time = datetime.now(UTC)
        timeout = spec.timeout_seconds or self._default_timeout_seconds
        self._prepare_workspace(spec, workdir)

        # 1. Initialize backend and providers
        init_args = ["init", "-no-color", "-input=false"]
        for k, v in sorted(spec.backend_config.items()):
            init_args.append(f"-backend-config={k}={v}")

        code, output = await self._run_command(init_args, workdir, spec.env, timeout)
        if code != 0:
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            return InfraProvisionResult(
                outputs={},
                success=False,
                duration_seconds=elapsed,
                error_message=f"Init failed (exit code {code}): {output}",
            )

        # 2. Apply plan
        apply_args = ["apply", "-auto-approve", "-no-color", "-input=false"]
        code, output = await self._run_command(apply_args, workdir, spec.env, timeout)
        if code != 0:
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            return InfraProvisionResult(
                outputs={},
                success=False,
                duration_seconds=elapsed,
                error_message=f"Apply failed (exit code {code}): {output}",
            )

        # 3. Extract outputs
        out_code, out_text = await self._run_command(
            ["output", "-json"], workdir, spec.env, timeout=30
        )
        extracted: dict[str, Any] = {}
        if out_code == 0 and out_text:
            with contextlib_suppress():
                parsed = json.loads(out_text)
                if isinstance(parsed, dict):
                    for k, val in parsed.items():
                        if isinstance(val, dict) and "value" in val:
                            extracted[k] = val["value"]
                        else:
                            extracted[k] = val

        elapsed = (datetime.now(UTC) - start_time).total_seconds()
        state_file = workdir / "terraform.tfstate"
        return InfraProvisionResult(
            outputs=extracted,
            success=True,
            duration_seconds=elapsed,
            state_file_path=str(state_file) if state_file.exists() else None,
        )

    async def destroy(self, spec: InfraPlanSpec, workdir: Path) -> InfraProvisionResult:
        """Destroy provisioned infrastructure resources."""
        start_time = datetime.now(UTC)
        timeout = spec.timeout_seconds or self._default_timeout_seconds
        destroy_args = ["destroy", "-auto-approve", "-no-color", "-input=false"]

        code, output = await self._run_command(destroy_args, workdir, spec.env, timeout)
        elapsed = (datetime.now(UTC) - start_time).total_seconds()
        if code != 0:
            return InfraProvisionResult(
                outputs={},
                success=False,
                duration_seconds=elapsed,
                error_message=f"Destroy failed (exit code {code}): {output}",
            )

        return InfraProvisionResult(
            outputs={},
            success=True,
            duration_seconds=elapsed,
        )

    async def plan(self, spec: InfraPlanSpec, workdir: Path) -> str:
        """Generate a dry-run execution plan string."""
        timeout = spec.timeout_seconds or self._default_timeout_seconds
        self._prepare_workspace(spec, workdir)
        code, output = await self._run_command(
            ["plan", "-no-color", "-input=false"], workdir, spec.env, timeout
        )
        if code != 0:
            msg = f"Plan dry-run failed with code {code}: {output}"
            raise HexaqueueWorkflowError(msg)
        return output


def contextlib_suppress():
    """Helper context manager suppressing parsing errors."""
    return contextlib.suppress(Exception)


__all__ = [
    "OpenTofuProvisionerAdapter",
]
