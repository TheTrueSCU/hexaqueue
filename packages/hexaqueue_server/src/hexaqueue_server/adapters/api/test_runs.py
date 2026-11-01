"""Distributed test slice execution REST API endpoints.

Notes/Architectural Intent:
    Receives partitioned test slice dispatch requests from pytest-hexaqueue,
    orchestrates parallel execution across local worker processes or remote
    cluster nodes, and aggregates granular test outcomes and telemetry into
    SliceOutcomeReport responses.
"""

import asyncio
import sys
import time
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


async def _execute_slice(
    slice_spec: TestSliceDispatch,
    worker_index: int,
    is_free_tier: bool,
) -> SliceOutcomeResponse:
    """Execute a single test slice in a dedicated worker subprocess."""
    worker_id = f"worker-local-{worker_index}"
    start_time = time.monotonic()
    outcomes: list[TestOutcomeRecord] = []

    if not slice_spec.test_nodeids:
        return SliceOutcomeResponse(
            slice_id=slice_spec.slice_id,
            slice_index=slice_spec.slice_index,
            worker_id=worker_id,
            provider="LOCAL",
            is_free_tier=is_free_tier,
            outcomes=[],
            duration_seconds=0.0,
        )

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *slice_spec.test_nodeids,
        "-o",
        "addopts=",
        "--tb=short",
        "-q",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        exit_code = proc.returncode
        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        default_outcome = "passed" if exit_code == 0 else "failed"
        slice_duration = max(0.001, time.monotonic() - start_time)
        per_item_duration = slice_duration / max(1, len(slice_spec.test_nodeids))

        for nid in slice_spec.test_nodeids:
            outcomes.append(
                TestOutcomeRecord(
                    nodeid=nid,
                    outcome=default_outcome,
                    duration_seconds=round(per_item_duration, 3),
                    stdout=stdout_text if exit_code != 0 else None,
                    stderr=stderr_text if exit_code != 0 else None,
                )
            )

        return SliceOutcomeResponse(
            slice_id=slice_spec.slice_id,
            slice_index=slice_spec.slice_index,
            worker_id=worker_id,
            provider="LOCAL",
            is_free_tier=is_free_tier,
            outcomes=outcomes,
            duration_seconds=round(slice_duration, 3),
        )
    except Exception as exc:
        slice_duration = max(0.001, time.monotonic() - start_time)
        for nid in slice_spec.test_nodeids:
            outcomes.append(
                TestOutcomeRecord(
                    nodeid=nid,
                    outcome="failed",
                    duration_seconds=0.0,
                    longrepr=str(exc),
                )
            )
        return SliceOutcomeResponse(
            slice_id=slice_spec.slice_id,
            slice_index=slice_spec.slice_index,
            worker_id=worker_id,
            provider="LOCAL",
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
        tasks = [_execute_slice(s, i, req.free_tier) for i, s in enumerate(req.slices)]
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
