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
import uuid
from contextlib import nullcontext
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_fastapi.adapters.dependencies import get_pipeline
from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_server.adapters.api.auth import get_auth_context


class TestSliceDispatch(BaseModel):
    """Specification of an execution partition assigned to a cluster worker."""

    __test__ = False
    model_config = ConfigDict(extra="ignore")

    slice_id: str
    slice_index: int
    total_slices: int
    test_nodeids: list[str] = Field(default_factory=list)
    total_estimated_duration: float = 0.0


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


class TestOutcomeRecord(BaseModel):
    """Execution outcome of a single test item within a slice."""

    __test__ = False
    model_config = ConfigDict(frozen=True, extra="forbid")

    duration_seconds: float = Field(default=0.0, ge=0.0)
    longrepr: str | None = None
    nodeid: str
    outcome: str
    stderr: str | None = None
    stdout: str | None = None


class SliceOutcomeResponse(BaseModel):
    """Aggregate execution report for a completed test slice."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    coverage_data: dict[str, Any] | None = None
    duration_seconds: float = Field(default=0.0, ge=0.0)
    is_free_tier: bool = True
    outcomes: list[TestOutcomeRecord] = Field(default_factory=list)
    provider: str = "LOCAL"
    slice_id: str
    slice_index: int
    worker_id: str


class TestRunDispatchResponse(BaseModel):
    """Response containing slice execution reports for the entire test session."""

    reports: list[SliceOutcomeResponse] = Field(default_factory=list)


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
    if workspace_dir and (workspace_dir / "pyproject.toml").exists():
        uv_path = shutil.which("uv")
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
        try:
            bundle = await collateral_service.get_bundle(collateral_id)
            bundle_path_str = bundle.active_uri or bundle.staging_uri
            if bundle_path_str:
                bundle_path = Path(bundle_path_str)
                if bundle_path.exists():
                    target_dir.parent.mkdir(parents=True, exist_ok=True)
                    if target_dir.exists():
                        shutil.rmtree(target_dir, ignore_errors=True)
                    target_dir.mkdir(parents=True, exist_ok=True)
                    with tarfile.open(bundle_path, "r:gz") as tar:
                        tar.extractall(path=target_dir, filter="data")
                    return target_dir
        except Exception:
            pass

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
    env = dict(os.environ)
    env.pop("HEXAQUEUE_CSP_PROVIDER", None)
    if coverage_sources:
        env["COVERAGE_FILE"] = cov_file

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
        workspace_dir = None
        collateral_svc = getattr(
            getattr(pipeline, "service", None), "collateral_service", None
        )
        if not is_container:
            workspace_dir = await _prepare_session_workspace(
                session_id=req.session_id,
                collateral_id=req.collateral_id,
                git_commit=req.git_commit,
                git_ref=req.git_ref,
                collateral_service=collateral_svc,
            )

        try:
            tasks = [
                _execute_slice(
                    s,
                    i,
                    req.free_tier,
                    is_container=is_container,
                    container_image=req.container_image,
                    coverage_sources=req.coverage_sources,
                    semaphore=semaphore,
                    workspace_dir=workspace_dir,
                )
                for i, s in enumerate(req.slices)
            ]
            reports = await asyncio.gather(*tasks)
            return TestRunDispatchResponse(reports=list(reports))
        finally:
            if workspace_dir is not None:
                await _cleanup_session_workspace(workspace_dir)

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
