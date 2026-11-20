"""Budget accounting, two-phase reservation, and cluster health REST endpoints.

Notes/Architectural Intent:
    Surfaces tenant credit balances, atomic two-phase budget reservation holds,
    incremental preemption segment settlements, unspent credit releases,
    cluster-wide telemetry and capacity health reports, and live controller
    burst-pool budget strategy management over OpenAPI.
"""

import os
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Request,
    Response,
    status,
)
from hexastack_core.ports.container import ContainerPort
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_fastapi.adapters.dependencies import get_pipeline
from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_core.domain.budget import ClusterHealthReport, TenantAccount
from hexaqueue_core.domain.cqrs import (
    BudgetReportResponse,
    GetBudgetReportQuery,
    GetClusterHealthQuery,
    GetTenantBalanceQuery,
    ReleaseBudgetCommand,
    ReserveBudgetCommand,
    SettleSegmentCommand,
)
from hexaqueue_server.adapters.api.auth import get_auth_context
from hexaqueue_server.adapters.api.common import _dispatch
from hexaqueue_server.domain.autoscaler import (
    BudgetAwareInstancePoolAutoscaler,
    BudgetStrategyMode,
    CreditPacingPolicy,
)
from hexaqueue_server.domain.lease_coordinator import SliceLeaseCoordinator


class BudgetStrategyUpdateRequest(BaseModel):
    """Request payload for updating the live controller budget strategy.

    Args:
        strategy: Target ``BudgetStrategyMode`` to activate on the autoscaler.
        total_credits_usd: Optional total credit pool override in USD.
        spent_credits_usd: Optional cumulative spend override in USD.
        reserve_credits_usd: Optional safety reserve override in USD.
        daily_cap_usd: Optional daily spend cap override in USD.
        hourly_cost_per_node_usd: Optional per-node hourly burn rate override.
        start_time: Optional credit window start timestamp in UTC.
        expiry_time: Optional credit window expiry timestamp in UTC.
        clear_expiry: When True, clears any configured ``expiry_time``.

    Notes/Architectural Intent:
        Omitted fields inherit the current active policy values so operators can
        toggle strategies (e.g. ``LINEAR_CREDIT_PACING`` -> ``FREE_TIER_ONLY``)
        without re-specifying credit balances or expiration timestamps.
    """

    model_config = ConfigDict(extra="forbid")

    strategy: BudgetStrategyMode = Field(description="Target budget strategy mode")
    total_credits_usd: float | None = Field(
        default=None, gt=0.0, description="Total credit allocation in USD"
    )
    spent_credits_usd: float | None = Field(
        default=None, ge=0.0, description="Cumulative spent credits in USD"
    )
    reserve_credits_usd: float | None = Field(
        default=None, ge=0.0, description="Safety reserve credits in USD"
    )
    daily_cap_usd: float | None = Field(
        default=None, ge=0.0, description="Daily USD spend cap"
    )
    hourly_cost_per_node_usd: float | None = Field(
        default=None, gt=0.0, description="Hourly USD burn rate per worker node"
    )
    start_time: datetime | None = Field(
        default=None, description="Credit window start timestamp in UTC"
    )
    expiry_time: datetime | None = Field(
        default=None, description="Credit expiration timestamp in UTC"
    )
    clear_expiry: bool = Field(
        default=False, description="Clear any previously set credit expiry timestamp"
    )


class BudgetStrategyStatusResponse(BaseModel):
    """Response payload reporting active burst-pool budget strategy and pacing metrics.

    Notes/Architectural Intent:
        Reflects whether a ``CreditPacingPolicy`` is currently active on the
        controller's ``BudgetAwareInstancePoolAutoscaler``, computed remaining
        spendable balance, daily allowance, recommended node ceiling, and whether
        updating the strategy triggered an immediate pool reconciliation.
    """

    configured: bool = Field(
        description="Whether an explicit CreditPacingPolicy is attached"
    )
    strategy: BudgetStrategyMode = Field(description="Active budget strategy mode")
    available_strategies: list[str] = Field(
        description="Supported BudgetStrategyMode values"
    )
    total_credits_usd: float | None = Field(
        default=None, description="Total credit allocation in USD"
    )
    spent_credits_usd: float | None = Field(
        default=None, description="Cumulative spent credits in USD"
    )
    reserve_credits_usd: float | None = Field(
        default=None, description="Safety reserve credits in USD"
    )
    spendable_remaining_usd: float | None = Field(
        default=None, description="Remaining spendable credits above reserve in USD"
    )
    daily_cap_usd: float | None = Field(
        default=None, description="Configured daily USD spend cap"
    )
    daily_allowance_usd: float | None = Field(
        default=None, description="Computed daily USD burst spend allowance"
    )
    hourly_cost_per_node_usd: float | None = Field(
        default=None, description="Estimated hourly USD burn rate per burst worker"
    )
    start_time: datetime | None = Field(
        default=None, description="Credit window start timestamp in UTC"
    )
    expiry_time: datetime | None = Field(
        default=None, description="Credit window expiration timestamp in UTC"
    )
    is_expired: bool = Field(
        default=False, description="True if credit expiration timestamp has passed"
    )
    recommended_max_nodes: int | None = Field(
        default=None,
        description="Recommended maximum burst worker nodes under current strategy",
    )
    reconcile_triggered: bool = Field(
        default=False,
        description="True if pool autoscaler reconciliation ran after update",
    )


def _normalize_utc(ts: datetime | None) -> datetime | None:
    """Attach UTC timezone to naive datetime values."""
    if ts is None:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def _read_max_pool_size() -> int:
    """Read configured hard burst-pool ceiling from HEXAQUEUE_OCI_MAX_POOL_SIZE."""
    raw_ceiling = os.environ.get("HEXAQUEUE_OCI_MAX_POOL_SIZE", "10").strip() or "10"
    try:
        return max(0, int(raw_ceiling))
    except ValueError:
        return 10


def _resolve_autoscaler_and_coordinator(
    request: Request,
) -> tuple[BudgetAwareInstancePoolAutoscaler, SliceLeaseCoordinator | None]:
    """Resolve active autoscaler and coordinator from DI container or app state."""
    container = getattr(request.app.state, "container", None)
    coordinator: SliceLeaseCoordinator | None = None
    if isinstance(container, ContainerPort) and SliceLeaseCoordinator in container:
        coordinator = container.resolve(SliceLeaseCoordinator)

    autoscaler: BudgetAwareInstancePoolAutoscaler | None = None
    if coordinator is not None and coordinator.autoscaler is not None:
        autoscaler = coordinator.autoscaler
    elif (
        isinstance(container, ContainerPort)
        and BudgetAwareInstancePoolAutoscaler in container
    ):
        autoscaler = container.resolve(BudgetAwareInstancePoolAutoscaler)
    else:
        autoscaler = getattr(request.app.state, "autoscaler", None)

    if autoscaler is None:
        autoscaler = BudgetAwareInstancePoolAutoscaler()

    if (
        isinstance(container, ContainerPort)
        and BudgetAwareInstancePoolAutoscaler not in container
    ):
        container.add_instance(
            autoscaler, declared_class=BudgetAwareInstancePoolAutoscaler
        )
    request.app.state.autoscaler = autoscaler
    return autoscaler, coordinator


def _merge_strategy_policy(
    existing: CreditPacingPolicy | None, req: BudgetStrategyUpdateRequest
) -> CreditPacingPolicy:
    """Merge partial budget strategy update request onto an existing policy."""
    base = existing or CreditPacingPolicy(strategy=req.strategy)
    expiry = (
        None
        if req.clear_expiry
        else (
            _normalize_utc(req.expiry_time)
            if req.expiry_time is not None
            else base.expiry_time
        )
    )
    start = (
        _normalize_utc(req.start_time)
        if req.start_time is not None
        else base.start_time
    )
    return CreditPacingPolicy(
        strategy=req.strategy,
        total_credits_usd=(
            req.total_credits_usd
            if req.total_credits_usd is not None
            else base.total_credits_usd
        ),
        spent_credits_usd=(
            req.spent_credits_usd
            if req.spent_credits_usd is not None
            else base.spent_credits_usd
        ),
        reserve_credits_usd=(
            req.reserve_credits_usd
            if req.reserve_credits_usd is not None
            else base.reserve_credits_usd
        ),
        daily_cap_usd=(
            req.daily_cap_usd if req.daily_cap_usd is not None else base.daily_cap_usd
        ),
        hourly_cost_per_node_usd=(
            req.hourly_cost_per_node_usd
            if req.hourly_cost_per_node_usd is not None
            else base.hourly_cost_per_node_usd
        ),
        start_time=start,
        expiry_time=expiry,
    )


def _build_strategy_status(
    policy: CreditPacingPolicy | None, *, reconcile_triggered: bool = False
) -> BudgetStrategyStatusResponse:
    """Build BudgetStrategyStatusResponse snapshot from an optional policy."""
    strategies = [mode.value for mode in BudgetStrategyMode]
    if policy is None:
        return BudgetStrategyStatusResponse(
            configured=False,
            strategy=BudgetStrategyMode.UNCONSTRAINED,
            available_strategies=strategies,
            reconcile_triggered=reconcile_triggered,
        )

    hard_ceiling = _read_max_pool_size()
    daily_allowance = (
        None
        if policy.strategy == BudgetStrategyMode.UNCONSTRAINED
        else policy.daily_allowance_usd()
    )
    return BudgetStrategyStatusResponse(
        configured=True,
        strategy=policy.strategy,
        available_strategies=strategies,
        total_credits_usd=policy.total_credits_usd,
        spent_credits_usd=policy.spent_credits_usd,
        reserve_credits_usd=policy.reserve_credits_usd,
        spendable_remaining_usd=round(policy.spendable_remaining_usd(), 2),
        daily_cap_usd=policy.daily_cap_usd,
        daily_allowance_usd=daily_allowance,
        hourly_cost_per_node_usd=policy.hourly_cost_per_node_usd,
        start_time=policy.start_time,
        expiry_time=policy.expiry_time,
        is_expired=policy.is_expired(),
        recommended_max_nodes=policy.recommended_max_nodes(hard_ceiling=hard_ceiling),
        reconcile_triggered=reconcile_triggered,
    )


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

    # 6. Columnar Budget Analytics Report
    @router.get(
        "/budget/report",
        response_model=BudgetReportResponse,
        summary="Retrieve zero-copy columnar budget and spend analytics report",
    )
    def get_budget_report(
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
        tenant_id: str | None = None,
        window_hours: int = 24,
        format: str = "json",
    ) -> BudgetReportResponse | Response:
        user_id, is_elevated = auth
        qry = GetBudgetReportQuery(
            tenant_id=tenant_id,
            window_hours=window_hours,
            format=format,
            user_id=user_id,
            elevate=is_elevated,
        )
        res = _dispatch(pipeline, qry)
        if isinstance(res, (bytes, bytearray)):
            media_type = "application/octet-stream"
            if format.lower() in ("arrow_ipc", "arrow"):
                media_type = "application/vnd.apache.arrow.stream"
            elif format.lower() == "parquet":
                media_type = "application/vnd.apache.parquet"
            elif format.lower() == "csv":
                media_type = "text/csv"
            return Response(content=res, media_type=media_type)
        return res

    # 7. Active Burst-Pool Budget Strategy (Read)
    @router.get(
        "/budget/strategy",
        response_model=BudgetStrategyStatusResponse,
        summary="Retrieve active burst-pool budget strategy and pacing telemetry",
    )
    def get_budget_strategy(
        request: Request,
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> BudgetStrategyStatusResponse:
        _ = auth
        autoscaler, _coordinator = _resolve_autoscaler_and_coordinator(request)
        return _build_strategy_status(autoscaler.credit_pacing)

    # 8. Active Burst-Pool Budget Strategy (Update at Runtime)
    @router.put(
        "/budget/strategy",
        response_model=BudgetStrategyStatusResponse,
        summary="Update active burst-pool budget strategy at runtime",
    )
    async def set_budget_strategy(
        request: Request,
        cmd: BudgetStrategyUpdateRequest,
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> BudgetStrategyStatusResponse:
        _user_id, is_elevated = auth
        if not is_elevated:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrative elevation required to modify cluster budget strategy.",
            )
        autoscaler, coordinator = _resolve_autoscaler_and_coordinator(request)
        new_policy = _merge_strategy_policy(autoscaler.credit_pacing, cmd)
        autoscaler.set_credit_pacing(new_policy)
        reconcile_triggered = False
        if coordinator is not None and coordinator.has_autoscaler:
            await coordinator.reconcile_capacity()
            reconcile_triggered = True
        return _build_strategy_status(
            new_policy, reconcile_triggered=reconcile_triggered
        )

    return router


__all__ = [
    "BudgetStrategyStatusResponse",
    "BudgetStrategyUpdateRequest",
    "create_budget_router",
]
