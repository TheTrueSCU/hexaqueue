"""Budget accounting, two-phase reservation, and cluster health REST endpoints.

Notes/Architectural Intent:
    Surfaces tenant credit balances, atomic two-phase budget reservation holds,
    incremental preemption segment settlements, unspent credit releases, and
    cluster-wide telemetry and capacity health reports over OpenAPI.
"""

from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    Path,
)
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_fastapi.adapters.dependencies import get_pipeline

from hexaqueue_core.domain.budget import ClusterHealthReport, TenantAccount
from hexaqueue_core.domain.cqrs import (
    GetClusterHealthQuery,
    GetTenantBalanceQuery,
    ReleaseBudgetCommand,
    ReserveBudgetCommand,
    SettleSegmentCommand,
)
from hexaqueue_server.adapters.api.auth import get_auth_context
from hexaqueue_server.adapters.api.common import _dispatch


def create_budget_router() -> APIRouter:
    """Construct APIRouter for budget reservations, segment settlements, and cluster health.

    Returns:
        APIRouter with endpoints for budget operations and cluster health telemetry.
    """
    router = APIRouter()

    # 1. Reserve Budget
    @router.post(
        "/budget/reserve",
        response_model=dict[str, Any],
        summary="Place a pre-emptive budget hold for job execution",
    )
    def reserve_budget(
        cmd: ReserveBudgetCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> dict[str, Any]:
        user_id, is_elevated = auth
        effective_cmd = ReserveBudgetCommand(
            tenant_id=cmd.tenant_id,
            job_id=cmd.job_id,
            estimated_credits=cmd.estimated_credits,
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pipeline, effective_cmd)

    # 2. Settle Preemption Segment
    @router.post(
        "/budget/settle-segment",
        response_model=dict[str, Any],
        summary="Settle an incremental execution segment upon preemption",
    )
    def settle_segment(
        cmd: SettleSegmentCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> dict[str, Any]:
        user_id, is_elevated = auth
        effective_cmd = SettleSegmentCommand(
            reservation_id=cmd.reservation_id,
            segment_credits=cmd.segment_credits,
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pipeline, effective_cmd)

    # 3. Release Budget Hold
    @router.post(
        "/budget/release",
        response_model=dict[str, Any],
        summary="Release an active budget hold in full without billing",
    )
    def release_budget(
        cmd: ReleaseBudgetCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> dict[str, Any]:
        user_id, is_elevated = auth
        effective_cmd = ReleaseBudgetCommand(
            reservation_id=cmd.reservation_id,
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pipeline, effective_cmd)

    # 4. Get Tenant Balance
    @router.get(
        "/budget/tenants/{tenant_id}",
        response_model=TenantAccount,
        summary="Retrieve tenant credit balance and active hold details",
    )
    def get_tenant_balance(
        tenant_id: Annotated[str, Path(description="Target tenant account ID")],
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> TenantAccount:
        user_id, is_elevated = auth
        qry = GetTenantBalanceQuery(
            tenant_id=tenant_id,
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pipeline, qry)

    # 5. Cluster Health Telemetry Report
    @router.get(
        "/cluster/health",
        response_model=ClusterHealthReport,
        summary="Retrieve point-in-time cluster capacity and health report",
    )
    def get_cluster_health(
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> ClusterHealthReport:
        user_id, is_elevated = auth
        qry = GetClusterHealthQuery(
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pipeline, qry)

    return router


__all__ = [
    "create_budget_router",
]
