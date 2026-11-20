"""Internal worker pool registration, pull leasing, and slice reporting REST endpoints.

Notes/Architectural Intent:
    Serves the worker-only interface listening on internal cluster ports (e.g. 8001
    over private VNIC) per the ADR-007 amendment. Validates incoming requests via the
    shared cluster join token (X-Hexaqueue-Join-Token) and orchestrates pull-based
    test slice execution through the SliceLeaseCoordinator.
"""

import os
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from hexastack_core.domain.exceptions import DependencyResolutionError
from hexastack_core.ports.container import ContainerPort
from pydantic import BaseModel, Field

from hexaqueue_core.domain.lease import (
    SliceLease,
    SliceReportPayload,
    WorkerRegistration,
)
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.domain.lease_coordinator import SliceLeaseCoordinator


def get_lease_coordinator(request: Request) -> SliceLeaseCoordinator:
    """Dependency provider resolving the active SliceLeaseCoordinator from DI container.

    Args:
        request: Incoming FastAPI Request providing application container.

    Returns:
        The SliceLeaseCoordinator instance registered in the application container.

    Raises:
        DependencyResolutionError: If SliceLeaseCoordinator is not registered in container.
    """
    container = getattr(request.app.state, "container", None)
    if isinstance(container, ContainerPort) and SliceLeaseCoordinator in container:
        return container.resolve(SliceLeaseCoordinator)
    msg = "SliceLeaseCoordinator is not registered in request.app.state.container"
    raise DependencyResolutionError(msg)


class WorkerHeartbeatRequest(BaseModel):
    """Worker pulse payload including currently leased task identifiers and telemetry."""

    active_lease_ids: list[str] = Field(
        default_factory=list, description="Lease IDs actively executing on this worker"
    )
    cpu_utilization_pct: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Observed worker CPU utilization (%)",
    )
    load_average: tuple[float, float, float] | None = Field(
        default=None,
        description="Observed system load averages (1m, 5m, 15m)",
    )
    memory_used_mb: int | None = Field(
        default=None, ge=0, description="Observed worker RAM used in MB"
    )
    memory_total_mb: int | None = Field(
        default=None, ge=0, description="Observed worker total RAM in MB"
    )
    scratch_used_mb: int | None = Field(
        default=None, ge=0, description="Observed worker scratch disk used in MB"
    )
    scratch_total_mb: int | None = Field(
        default=None, ge=0, description="Observed worker total scratch disk in MB"
    )


class LeaseQueryRequest(BaseModel):
    """Parameters for long-polling slice leases."""

    available_ocpus: int = Field(default=1, ge=1, description="Available worker OCPUs")
    timeout_seconds: float = Field(
        default=5.0, ge=0.0, le=60.0, description="Long-poll timeout in seconds"
    )


def verify_join_token(
    x_hexaqueue_join_token: Annotated[str | None, Header()] = None,
) -> None:
    """Verify cluster join token from request header against environment secret.

    Raises:
        HTTPException: 403 Forbidden if join token does not match configured secret.
    """
    expected_token = os.environ.get("HEXAQUEUE_JOIN_TOKEN")
    if expected_token and x_hexaqueue_join_token != expected_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-Hexaqueue-Join-Token header",
        )


def create_worker_pool_router(
    coordinator: SliceLeaseCoordinator | None = None,
) -> APIRouter:
    """Construct APIRouter for internal worker node registration, pull leasing, and reporting.

    Args:
        coordinator: Optional SliceLeaseCoordinator override.

    Returns:
        APIRouter bound to worker pull operations.
    """
    router = APIRouter(dependencies=[Depends(verify_join_token)])

    def _get_coord(request: Request) -> SliceLeaseCoordinator:
        if coordinator is not None:
            return coordinator
        return get_lease_coordinator(request)

    # 1. Worker Registration
    @router.post(
        "/worker/register",
        status_code=status.HTTP_201_CREATED,
        summary="Register a compute worker node with the cluster coordinator",
    )
    async def register_worker(
        reg: WorkerRegistration,
        coord: Annotated[SliceLeaseCoordinator, Depends(_get_coord)],
    ) -> dict[str, str]:
        await coord.register_worker(reg)
        return {"status": "registered", "worker_id": reg.worker_id}

    # 2. Worker Heartbeat
    @router.post(
        "/worker/{worker_id}/heartbeat",
        summary="Record worker heartbeat and renew active leases",
    )
    async def worker_heartbeat(
        worker_id: str,
        coord: Annotated[SliceLeaseCoordinator, Depends(_get_coord)],
        req: WorkerHeartbeatRequest | None = None,
    ) -> dict[str, Any]:
        active_ids = req.active_lease_ids if req else None
        telemetry: dict[str, Any] | None = None
        if req is not None:
            raw_telemetry: dict[str, Any] = {
                "cpu_utilization_pct": req.cpu_utilization_pct,
                "load_average": req.load_average,
                "memory_used_mb": req.memory_used_mb,
                "memory_total_mb": req.memory_total_mb,
                "scratch_used_mb": req.scratch_used_mb,
                "scratch_total_mb": req.scratch_total_mb,
            }
            telemetry = {k: v for k, v in raw_telemetry.items() if v is not None}
        acknowledged = await coord.record_heartbeat(
            worker_id, active_ids, telemetry=telemetry
        )
        if not acknowledged:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Worker '{worker_id}' is not registered",
            )
        return {"status": "ok", "worker_id": worker_id}

    # 3. Pull/Lease Slice
    @router.post(
        "/worker/{worker_id}/lease",
        response_model=SliceLease | None,
        summary="Long-poll for a pending test slice lease",
    )
    async def lease_slice(
        worker_id: str,
        coord: Annotated[SliceLeaseCoordinator, Depends(_get_coord)],
        params: LeaseQueryRequest | None = None,
    ) -> Any:
        ocpus = params.available_ocpus if params else 1
        timeout = params.timeout_seconds if params else 5.0
        lease = await coord.lease_slice(
            worker_id=worker_id,
            available_ocpus=ocpus,
            timeout_seconds=timeout,
        )
        if lease is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        return lease

    # 4. Report Slice Outcome
    @router.post(
        "/worker/{worker_id}/report",
        summary="Report completed slice outcomes and coverage collateral",
    )
    async def report_slice(
        worker_id: str,
        report: SliceReportPayload,
        coord: Annotated[SliceLeaseCoordinator, Depends(_get_coord)],
    ) -> dict[str, str]:
        accepted = await coord.report_slice_outcome(report)
        if not accepted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Lease '{report.lease_id}' is missing, already completed, or revoked",
            )
        return {"status": "recorded", "slice_id": report.slice_id}

    # 4b. Append Incremental Worker Log Chunks
    @router.post(
        "/worker/{worker_id}/logs/{job_id}",
        summary="Append live execution log chunks for a leased job",
    )
    async def append_worker_logs(
        worker_id: str,
        job_id: str,
        chunks: list[LogChunk],
        coord: Annotated[SliceLeaseCoordinator, Depends(_get_coord)],
    ) -> dict[str, Any]:
        total = await coord.append_log_chunks(job_id, chunks)
        return {
            "status": "ok",
            "worker_id": worker_id,
            "job_id": job_id,
            "total_chunks": total,
        }

    # 5. Worker Pool Stats
    @router.get(
        "/worker/stats",
        summary="Get active worker pool capacity and queue depth metrics",
    )
    def worker_pool_stats(
        coord: Annotated[SliceLeaseCoordinator, Depends(_get_coord)],
    ) -> dict[str, int]:
        return {
            "active_workers": coord.active_worker_count,
            "pending_slices": coord.pending_count,
            "active_leases": coord.active_lease_count,
        }

    return router


__all__ = [
    "create_worker_pool_router",
    "get_lease_coordinator",
]
