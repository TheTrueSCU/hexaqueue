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
    Response,
    status,
)
from pydantic import BaseModel, Field

from hexaqueue_core.domain.lease import (
    SliceLease,
    SliceReportPayload,
    WorkerRegistration,
)
from hexaqueue_server.domain.lease_coordinator import SliceLeaseCoordinator

# Module-level default singleton for runtime wiring
_DEFAULT_COORDINATOR: SliceLeaseCoordinator | None = None


def _build_default_coordinator() -> SliceLeaseCoordinator:
    """Build central coordinator wired with OCI autoscaler and storage if configured."""
    pool_id = os.environ.get("HEXAQUEUE_OCI_INSTANCE_POOL_ID") or os.environ.get(
        "HEXAQUEUE_INSTANCE_POOL_ID"
    )
    autoscaler = None
    storage_port = None
    if os.environ.get("HEXAQUEUE_CSP_PROVIDER") == "OCI" or pool_id:
        try:
            from hexaqueue_core.adapters.storage.oci import OciPresignedStorageAdapter
            from hexaqueue_core.domain.credentials import OciCredentialsConfig
            from hexaqueue_server.adapters.cloud.oci import OciInstancePoolAdapter
            from hexaqueue_server.domain.autoscaler import (
                BudgetAwareInstancePoolAutoscaler,
            )

            creds = OciCredentialsConfig(use_instance_principals=True)
            if pool_id:
                gov = OciInstancePoolAdapter.from_credentials(credentials=creds)
                autoscaler = BudgetAwareInstancePoolAutoscaler(governors={pool_id: gov})
            bucket = (
                os.environ.get("HEXAQUEUE_COLLATERAL_BUCKET") or "hexaqueue-collateral"
            )
            storage_port = OciPresignedStorageAdapter.from_credentials(
                credentials=creds,
                bucket_name=bucket,
            )
        except Exception:
            autoscaler = None
            storage_port = None

    return SliceLeaseCoordinator(
        storage_port=storage_port,
        autoscaler=autoscaler,
        pool_id=pool_id,
    )


def get_lease_coordinator() -> SliceLeaseCoordinator:
    """Dependency provider for the central SliceLeaseCoordinator singleton."""
    global _DEFAULT_COORDINATOR
    if _DEFAULT_COORDINATOR is None:
        _DEFAULT_COORDINATOR = _build_default_coordinator()
    return _DEFAULT_COORDINATOR


def set_lease_coordinator(coordinator: SliceLeaseCoordinator | None) -> None:
    """Set or override the global SliceLeaseCoordinator singleton."""
    global _DEFAULT_COORDINATOR
    _DEFAULT_COORDINATOR = coordinator


class WorkerHeartbeatRequest(BaseModel):
    """Worker pulse payload including currently leased task identifiers."""

    active_lease_ids: list[str] = Field(
        default_factory=list, description="Lease IDs actively executing on this worker"
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

    def _coord() -> SliceLeaseCoordinator:
        return coordinator or get_lease_coordinator()

    # 1. Worker Registration
    @router.post(
        "/worker/register",
        status_code=status.HTTP_201_CREATED,
        summary="Register a compute worker node with the cluster coordinator",
    )
    async def register_worker(
        reg: WorkerRegistration,
    ) -> dict[str, str]:
        coord = _coord()
        await coord.register_worker(reg)
        return {"status": "registered", "worker_id": reg.worker_id}

    # 2. Worker Heartbeat
    @router.post(
        "/worker/{worker_id}/heartbeat",
        summary="Record worker heartbeat and renew active leases",
    )
    async def worker_heartbeat(
        worker_id: str,
        req: WorkerHeartbeatRequest | None = None,
    ) -> dict[str, Any]:
        coord = _coord()
        active_ids = req.active_lease_ids if req else None
        acknowledged = await coord.record_heartbeat(worker_id, active_ids)
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
        params: LeaseQueryRequest | None = None,
    ) -> Any:
        coord = _coord()
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
    ) -> dict[str, str]:
        coord = _coord()
        accepted = await coord.report_slice_outcome(report)
        if not accepted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Lease '{report.lease_id}' is missing, already completed, or revoked",
            )
        return {"status": "recorded", "slice_id": report.slice_id}

    # 5. Worker Pool Stats
    @router.get(
        "/worker/stats",
        summary="Get active worker pool capacity and queue depth metrics",
    )
    def worker_pool_stats() -> dict[str, int]:
        coord = _coord()
        return {
            "active_workers": coord.active_worker_count,
            "pending_slices": coord.pending_count,
            "active_leases": coord.active_lease_count,
        }

    return router


__all__ = [
    "create_worker_pool_router",
    "get_lease_coordinator",
    "set_lease_coordinator",
]
