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
import time
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
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
    pool: str = "default"
    free_tier: bool = False
    container: bool = False
    container_image: str | None = None
    coverage_sources: list[str] = Field(default_factory=list)
    slices: list[TestSliceDispatch] = Field(default_factory=list)
    bundle: dict[str, Any] | None = None


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
        cmd = [
            container_bin,
            "run",
            "--rm",
            "--name",
            f"hq-slice-{slice_spec.slice_id}-{unique_suffix}",
            "-v",
            f"{Path.cwd()}:/workspace",
            "-w",
            "/workspace",
            image,
            "pytest",
            *slice_spec.test_nodeids,
            "-o",
            "addopts=",
            "--tb=short",
            "-q",
            *cov_flags,
        ]
        return cmd, provider, worker_id

    provider = "LOCAL"
    worker_id = f"worker-local-{worker_index}"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *slice_spec.test_nodeids,
        "-o",
        "addopts=",
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


async def _execute_slice(
    slice_spec: TestSliceDispatch,
    worker_index: int,
    is_free_tier: bool,
    is_container: bool = False,
    container_image: str | None = None,
    coverage_sources: list[str] | None = None,
) -> SliceOutcomeResponse:
    """Execute a single test slice in a dedicated worker subprocess or container."""
    cmd, provider, worker_id = _build_slice_cmd(
        slice_spec,
        worker_index,
        is_container,
        container_image,
        coverage_sources=coverage_sources,
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
    if coverage_sources:
        env["COVERAGE_FILE"] = cov_file

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
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
            cov_path = Path(cov_file)
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
    ) -> TestRunDispatchResponse:
        """Receive test slices and execute them concurrently across worker nodes."""
        is_container = req.container or req.pool == "container"
        tasks = [
            _execute_slice(
                s,
                i,
                req.free_tier,
                is_container=is_container,
                container_image=req.container_image,
                coverage_sources=req.coverage_sources,
            )
            for i, s in enumerate(req.slices)
        ]
        reports = await asyncio.gather(*tasks)
        return TestRunDispatchResponse(reports=list(reports))

    return router


__all__ = [
    "create_test_runs_router",
    "SliceOutcomeResponse",
    "TestOutcomeRecord",
    "TestRunDispatchRequest",
    "TestRunDispatchResponse",
    "TestSliceDispatch",
]
