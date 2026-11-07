"""Distributed test slice execution REST API endpoints.

Notes/Architectural Intent:
    Receives partitioned test slice dispatch requests from pytest-hexaqueue,
    orchestrates parallel execution across local worker processes or remote
    cluster nodes, and aggregates granular test outcomes and telemetry into
    SliceOutcomeReport responses.
"""

import asyncio
import base64
import os
import shutil
import sys
import tarfile
import time
import urllib.request
import uuid
from contextlib import nullcontext, suppress
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_fastapi.adapters.dependencies import get_pipeline
from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_core.domain.lease import (
    SliceOutcomeResponse,
    TestOutcomeRecord,
    TestSliceDispatch,
)
from hexaqueue_server.adapters.api.auth import get_auth_context
from hexaqueue_server.adapters.api.worker_pool import get_lease_coordinator


class TestRunDispatchRequest(BaseModel):
    """Distributed test run dispatch request payload."""

    __test__ = False
    model_config = ConfigDict(extra="ignore")

    session_id: str
    collateral_id: str | None = None
    pool: str = "default"
    free_tier: bool = False
    container: bool = False
    container_image: str | None = None
    coverage_sources: list[str] = Field(default_factory=list)
    slices: list[TestSliceDispatch] = Field(default_factory=list)
    bundle: dict[str, Any] | None = None
    git_commit: str | None = None
    git_ref: str | None = None


class TestRunDispatchResponse(BaseModel):
    """Response containing slice execution reports for the entire test session."""

    reports: list[SliceOutcomeResponse] = Field(default_factory=list)


_UV_SYNC_LOCK = asyncio.Lock()


def _find_uv_binary() -> str | None:
    """Locate the uv executable on PATH or standard user installation directories."""
    found = shutil.which("uv")
    if found:
        return found
    for candidate in (
        Path.home() / ".local" / "bin" / "uv",
        Path.home() / ".cargo" / "bin" / "uv",
        Path("/usr/local/bin/uv"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


async def _sync_workspace_environment(workspace_dir: Path) -> None:
    """Synchronize a uv-managed workspace environment once prior to slice execution."""
    if (
        not (workspace_dir / "pyproject.toml").exists()
        or not (workspace_dir / "uv.lock").exists()
    ):
        return
    uv_bin = _find_uv_binary()
    if not uv_bin:
        return
    sync_env = dict(os.environ)
    sync_env.pop("VIRTUAL_ENV", None)
    sync_env.pop("PYTHONPATH", None)
    async with _UV_SYNC_LOCK:
        try:
            proc = await asyncio.create_subprocess_exec(
                uv_bin,
                "sync",
                "--all-packages",
                "--all-extras",
                "--all-groups",
                cwd=str(workspace_dir),
                env=sync_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except Exception:
            pass


def _build_slice_cmd(
    slice_spec: TestSliceDispatch,
    worker_index: int,
    is_container: bool,
    container_image: str | None,
    coverage_sources: list[str] | None = None,
    workspace_dir: Path | None = None,
) -> tuple[list[str], str, str]:
    """Construct execution command line, provider name, and worker ID for a slice."""
    cov_flags: list[str] = []
    if coverage_sources:
        for src in coverage_sources:
            cov_flags.append(f"--cov={src}")
        cov_flags.extend(["--cov-report=", "--cov-fail-under=0"])

    if is_container:
        container_bin = shutil.which("docker") or shutil.which("podman") or "docker"
        image = container_image or "hexaqueue-worker:latest"
        provider = "CONTAINER"
        worker_id = f"worker-container-{worker_index}"
        unique_suffix = uuid.uuid4().hex[:8]
        host_dir = workspace_dir or Path.cwd()
        cmd = [
            container_bin,
            "run",
            "--rm",
            "--name",
            f"hq-slice-{slice_spec.slice_id}-{unique_suffix}",
            "-v",
            f"{host_dir}:/workspace",
            "-w",
            "/workspace",
            image,
            "pytest",
            *slice_spec.test_nodeids,
            "-o",
            "addopts=",
            "-o",
            "consider_namespace_packages=true",
            "-p",
            "no:cacheprovider",
            "--tb=short",
            "-q",
            *cov_flags,
        ]
        return cmd, provider, worker_id

    provider = os.getenv("HEXAQUEUE_CSP_PROVIDER", "LOCAL")
    worker_id = f"worker-{provider.lower()}-{worker_index}"

    pytest_bin = sys.executable
    pytest_args = ["-m", "pytest"]
    if workspace_dir:
        venv_python = workspace_dir / ".venv" / "bin" / "python"
        if venv_python.is_file():
            pytest_bin = str(venv_python)
        elif (workspace_dir / "pyproject.toml").exists():
            uv_path = _find_uv_binary()
            if uv_path:
                pytest_bin = uv_path
                pytest_args = ["run", "--directory", str(workspace_dir), "pytest"]

    cmd = [
        pytest_bin,
        *pytest_args,
        *slice_spec.test_nodeids,
        "-o",
        "addopts=",
        "-o",
        "consider_namespace_packages=true",
        "-p",
        "no:cacheprovider",
        "--tb=short",
        "-q",
        *cov_flags,
    ]
    return cmd, provider, worker_id


def _create_outcome_records(
    test_nodeids: list[str],
    outcome: str,
    duration: float,
    stdout: str | None = None,
    stderr: str | None = None,
    longrepr: str | None = None,
) -> list[TestOutcomeRecord]:
    """Create per-test outcome records partitioned across a slice."""
    per_item_duration = duration / max(1, len(test_nodeids))
    return [
        TestOutcomeRecord(
            nodeid=nid,
            outcome=outcome,
            duration_seconds=round(per_item_duration, 3),
            stdout=stdout,
            stderr=stderr,
            longrepr=longrepr,
        )
        for nid in test_nodeids
    ]


def get_worker_semaphore(request: Request) -> asyncio.Semaphore:
    """FastAPI dependency provider resolving the application-scoped worker semaphore.

    Args:
        request: Incoming FastAPI Request object.

    Returns:
        asyncio.Semaphore instance attached to application state.

    Raises:
        None.

    Notes/Architectural Intent:
        Enforces resource boundaries by serializing or concurrency-limiting slice executions
        against detected CPU cores, preventing process thrashing on large batch submissions.
    """
    sem = getattr(request.app.state, "worker_semaphore", None)
    if isinstance(sem, asyncio.Semaphore):
        return sem
    total_cores = os.cpu_count() or 4
    new_sem = asyncio.Semaphore(max(1, total_cores))
    request.app.state.worker_semaphore = new_sem
    return new_sem


async def _fetch_git_target(
    root: Path, git_commit: str | None, git_ref: str | None
) -> None:
    """Fetch remote git commit or ref into local repository cache if needed."""
    if not git_ref and not git_commit:
        return
    ref_spec = f"{git_ref}:ci-target" if git_ref else git_commit
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "fetch",
            "origin",
            str(ref_spec),
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
    except Exception:
        pass


async def _resolve_bundle_path(
    collateral_id: str,
    collateral_service: Any,
) -> str | None:
    """Resolve local path or remote download PAR URL for a collateral bundle.

    Args:
        collateral_id: CAS bundle identifier.
        collateral_service: CollateralServicePort instance.

    Returns:
        Local path or remote HTTPS URL string, or None if unresolved.
    """
    bundle = await collateral_service.get_bundle(collateral_id)
    bundle_path_str = bundle.active_uri or bundle.staging_uri

    if not bundle_path_str or (
        not bundle_path_str.startswith("http")
        and not Path(bundle_path_str.removeprefix("file://")).exists()
    ):
        get_url_fn = getattr(collateral_service, "get_download_url", None)
        if callable(get_url_fn):
            dl_url = await get_url_fn(collateral_id)
            if dl_url and dl_url.startswith("http"):
                return str(dl_url)
    return bundle_path_str


async def _unpack_bundle_archive(bundle_path_str: str, target_dir: Path) -> bool:
    """Extract remote HTTP tarball or local archive into target directory.

    Args:
        bundle_path_str: Local file path or remote HTTP PAR URL.
        target_dir: Target directory path.

    Returns:
        True if successfully extracted, False otherwise.
    """
    if bundle_path_str.startswith(("http://", "https://")):

        def _fetch_and_unpack() -> None:
            with (
                urllib.request.urlopen(  # noqa: S310
                    bundle_path_str, timeout=60
                ) as resp,
                tarfile.open(fileobj=resp, mode="r|gz") as tar,
            ):
                tar.extractall(path=target_dir, filter="data")

        await asyncio.to_thread(_fetch_and_unpack)
        return True

    clean_path = Path(bundle_path_str.removeprefix("file://"))
    if clean_path.exists():
        with tarfile.open(clean_path, "r:gz") as tar:
            tar.extractall(path=target_dir, filter="data")
        return True
    return False


async def _extract_collateral_workspace(
    collateral_id: str,
    collateral_service: Any,
    target_dir: Path,
) -> bool:
    """Download or read collateral bundle archive and extract into target workspace directory.

    Args:
        collateral_id: CAS collateral bundle identifier.
        collateral_service: Injected collateral service port.
        target_dir: Destination workspace root directory.

    Returns:
        True if successfully unpacked, False otherwise.

    Notes/Architectural Intent:
        Supports both local filesystem paths and remote Pre-Authenticated Requests (PARs)
        over HTTPS (OCI Object Storage).
    """
    try:
        bundle_path_str = await _resolve_bundle_path(collateral_id, collateral_service)
        if not bundle_path_str:
            return False

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        target_dir.mkdir(parents=True, exist_ok=True)

        unpacked = await _unpack_bundle_archive(bundle_path_str, target_dir)
        if unpacked:
            await _sync_workspace_environment(target_dir)
            return True
    except Exception:
        pass
    return False


async def _prepare_session_workspace(
    session_id: str,
    collateral_id: str | None = None,
    git_commit: str | None = None,
    git_ref: str | None = None,
    repo_root: Path | None = None,
    collateral_service: Any = None,
) -> Path | None:
    """Create an isolated, ephemeral workspace for session execution."""
    target_dir = Path("/tmp/hexaqueue/runs") / session_id

    # 1. Collateral-based workspace transport (client code under test)
    if collateral_id and collateral_service:
        success = await _extract_collateral_workspace(
            collateral_id, collateral_service, target_dir
        )
        if success:
            return target_dir

    # 2. Fallback to Git worktree (for server self-dogfooding)
    root = repo_root or Path.cwd()
    if not (root / ".git").exists():
        return None

    try:
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        if target_dir.exists():
            await _cleanup_session_workspace(target_dir, repo_root=root)

        await _fetch_git_target(root, git_commit, git_ref)

        target_ref = git_commit or ("ci-target" if git_ref else "HEAD")
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "worktree",
            "add",
            "--detach",
            str(target_dir),
            target_ref,
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode == 0:
            return target_dir

        fallback_proc = await asyncio.create_subprocess_exec(
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "worktree",
            "add",
            "--detach",
            str(target_dir),
            "HEAD",
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await fallback_proc.communicate()
        if fallback_proc.returncode == 0:
            return target_dir
    except Exception:
        pass
    return None


async def _cleanup_session_workspace(
    workspace_dir: Path | None, repo_root: Path | None = None
) -> None:
    """Tear down and prune an ephemeral workspace."""
    if not workspace_dir or not workspace_dir.exists():
        return
    root = repo_root or Path.cwd()
    if (root / ".git").exists():
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "worktree",
                "remove",
                "--force",
                str(workspace_dir),
                cwd=str(root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except Exception:
            pass
    shutil.rmtree(workspace_dir, ignore_errors=True)


def _configure_slice_env(
    workspace_dir: Path | None,
    cov_file: str,
    coverage_sources: list[str] | None,
) -> dict[str, str]:
    """Build isolated subprocess environment variables for a worker test slice."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("HEXAQUEUE_")}
    if workspace_dir:
        src_paths: list[str] = [
            str(p) for p in sorted((workspace_dir / "packages").glob("*/src"))
        ]
        if (workspace_dir / "src").is_dir():
            src_paths.append(str(workspace_dir / "src"))
        src_paths.append(str(workspace_dir))
        env["PYTHONPATH"] = os.pathsep.join(src_paths)
        if (workspace_dir / ".venv" / "bin").is_dir():
            venv_dir = workspace_dir / ".venv"
            env["VIRTUAL_ENV"] = str(venv_dir)
            env["PATH"] = f"{venv_dir / 'bin'}:{env.get('PATH', '')}"
    if coverage_sources:
        env["COVERAGE_FILE"] = cov_file
    return env


async def _execute_slice(
    slice_spec: TestSliceDispatch,
    worker_index: int,
    is_free_tier: bool,
    is_container: bool = False,
    container_image: str | None = None,
    coverage_sources: list[str] | None = None,
    semaphore: asyncio.Semaphore | None = None,
    workspace_dir: Path | None = None,
) -> SliceOutcomeResponse:
    """Execute a single test slice in a dedicated worker subprocess or container."""
    cmd, provider, worker_id = _build_slice_cmd(
        slice_spec,
        worker_index,
        is_container,
        container_image,
        coverage_sources=coverage_sources,
        workspace_dir=workspace_dir,
    )
    start_time = time.monotonic()

    if not slice_spec.test_nodeids:
        return SliceOutcomeResponse(
            slice_id=slice_spec.slice_id,
            slice_index=slice_spec.slice_index,
            worker_id=worker_id,
            provider=provider,
            is_free_tier=is_free_tier,
            outcomes=[],
            duration_seconds=0.0,
        )

    cov_file = f".coverage.hq.{slice_spec.slice_id}"
    env = _configure_slice_env(workspace_dir, cov_file, coverage_sources)

    try:
        async with semaphore if semaphore is not None else nullcontext():
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(workspace_dir) if workspace_dir else None,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await proc.communicate()
        exit_code = proc.returncode
        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        default_outcome = "passed" if exit_code == 0 else "failed"
        slice_duration = max(0.001, time.monotonic() - start_time)

        outcomes = _create_outcome_records(
            slice_spec.test_nodeids,
            outcome=default_outcome,
            duration=slice_duration,
            stdout=stdout_text if exit_code != 0 else None,
            stderr=stderr_text if exit_code != 0 else None,
        )

        cov_data: dict[str, Any] | None = None
        if coverage_sources:
            cov_path = (workspace_dir / cov_file) if workspace_dir else Path(cov_file)
            if cov_path.exists():
                file_bytes = cov_path.read_bytes()
                cov_data = {
                    "sqlite_b64": base64.b64encode(file_bytes).decode("ascii"),
                    "workspace_root": "/workspace"
                    if is_container
                    else str((workspace_dir or Path.cwd()).resolve()),
                }

        return SliceOutcomeResponse(
            slice_id=slice_spec.slice_id,
            slice_index=slice_spec.slice_index,
            worker_id=worker_id,
            provider=provider,
            is_free_tier=is_free_tier,
            coverage_data=cov_data,
            outcomes=outcomes,
            duration_seconds=round(slice_duration, 3),
        )
    except Exception as exc:
        slice_duration = max(0.001, time.monotonic() - start_time)
        outcomes = _create_outcome_records(
            slice_spec.test_nodeids,
            outcome="failed",
            duration=0.0,
            longrepr=str(exc),
        )
        return SliceOutcomeResponse(
            slice_id=slice_spec.slice_id,
            slice_index=slice_spec.slice_index,
            worker_id=worker_id,
            provider=provider,
            is_free_tier=is_free_tier,
            outcomes=outcomes,
            duration_seconds=round(slice_duration, 3),
        )


async def _dispatch_remote_slices(
    req: TestRunDispatchRequest,
    coord: Any,
    collateral_svc: Any,
    is_container: bool,
) -> list[SliceOutcomeResponse]:
    """Dispatch slices to remote worker pool via SliceLeaseCoordinator.

    Args:
        req: Test run dispatch request payload.
        coord: SliceLeaseCoordinator instance.
        collateral_svc: Optional collateral service instance.
        is_container: Whether container execution is requested.

    Returns:
        List of completed SliceOutcomeResponse objects.
    """
    if getattr(coord, "_collateral_service", None) is None:
        coord._collateral_service = collateral_svc
    completion_ev = await coord.enqueue_session_slices(
        session_id=req.session_id,
        slices=req.slices,
        collateral_id=req.collateral_id,
        coverage_sources=req.coverage_sources,
        container=is_container,
        container_image=req.container_image,
    )
    est_total = sum(s.total_estimated_duration for s in req.slices)
    timeout = max(300.0, est_total * 2.0)
    with suppress(TimeoutError):
        await asyncio.wait_for(completion_ev.wait(), timeout=timeout)
    return await coord.get_session_reports(req.session_id)


async def _dispatch_local_slices(
    *,
    session_id: str,
    collateral_id: str | None,
    git_commit: str | None,
    git_ref: str | None,
    collateral_svc: Any,
    slices: list[TestSliceDispatch],
    free_tier: bool,
    is_container: bool,
    container_image: str | None,
    coverage_sources: list[str],
    semaphore: asyncio.Semaphore,
) -> list[SliceOutcomeResponse]:
    """Execute remaining slices on local worker host.

    Args:
        session_id: Session identifier.
        collateral_id: Optional collateral bundle ID.
        git_commit: Optional git commit.
        git_ref: Optional git ref.
        collateral_svc: Optional collateral service.
        slices: List of test slices to execute.
        free_tier: Whether free tier limits apply.
        is_container: Whether container isolation is requested.
        container_image: Container image name.
        coverage_sources: List of coverage target packages.
        semaphore: Concurrency limiter semaphore.

    Returns:
        List of locally executed SliceOutcomeResponse objects.
    """
    workspace_dir = None
    if not is_container:
        workspace_dir = await _prepare_session_workspace(
            session_id=session_id,
            collateral_id=collateral_id,
            git_commit=git_commit,
            git_ref=git_ref,
            collateral_service=collateral_svc,
        )

    try:
        tasks = [
            _execute_slice(
                s,
                i,
                free_tier,
                is_container=is_container,
                container_image=container_image,
                coverage_sources=coverage_sources,
                semaphore=semaphore,
                workspace_dir=workspace_dir,
            )
            for i, s in enumerate(slices)
        ]
        local_reports = await asyncio.gather(*tasks)
        return list(local_reports)
    finally:
        if workspace_dir is not None:
            await _cleanup_session_workspace(workspace_dir)


def create_test_runs_router() -> APIRouter:
    """Construct APIRouter for distributed test run operations.

    Returns:
        APIRouter with endpoints for distributed test slicing and execution.
    """
    router = APIRouter()

    @router.post(
        "/test/runs",
        response_model=TestRunDispatchResponse,
        summary="Dispatch distributed test slices across cluster workers",
    )
    async def dispatch_test_run(
        req: TestRunDispatchRequest,
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
        semaphore: Annotated[asyncio.Semaphore, Depends(get_worker_semaphore)],
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
    ) -> TestRunDispatchResponse:
        """Receive test slices and execute them concurrently across worker nodes."""
        is_container = req.container or req.pool == "container"
        collateral_svc = getattr(
            getattr(pipeline, "service", None), "collateral_service", None
        )

        coord = get_lease_coordinator()
        reports: list[SliceOutcomeResponse] = []
        remaining_slices = req.slices

        # 1. Dispatch through cluster worker pool if workers are active
        if coord.active_worker_count > 0:
            pool_reports = await _dispatch_remote_slices(
                req, coord, collateral_svc, is_container
            )
            reports.extend(pool_reports)
            completed_ids = {r.slice_id for r in pool_reports}
            remaining_slices = [
                s for s in req.slices if s.slice_id not in completed_ids
            ]

        # 2. Execute any remaining slices locally as fallback
        if remaining_slices:
            local_reports = await _dispatch_local_slices(
                session_id=req.session_id,
                collateral_id=req.collateral_id,
                git_commit=req.git_commit,
                git_ref=req.git_ref,
                collateral_svc=collateral_svc,
                slices=remaining_slices,
                free_tier=req.free_tier,
                is_container=is_container,
                container_image=req.container_image,
                coverage_sources=req.coverage_sources,
                semaphore=semaphore,
            )
            reports.extend(local_reports)

        order = {s.slice_id: idx for idx, s in enumerate(req.slices)}
        reports.sort(key=lambda r: order.get(r.slice_id, 0))
        return TestRunDispatchResponse(reports=reports)

    return router


__all__ = [
    "create_test_runs_router",
    "get_worker_semaphore",
    "SliceOutcomeResponse",
    "TestOutcomeRecord",
    "TestRunDispatchRequest",
    "TestRunDispatchResponse",
    "TestSliceDispatch",
]
