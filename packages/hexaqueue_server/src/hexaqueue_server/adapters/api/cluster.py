"""Cluster queue stats, fair-share hierarchy, DLQ, collateral, and budget REST endpoints.

Notes/Architectural Intent:
    Surfaces system-wide operational metrics, fair-share deficit accounting,
    dead-letter queue inspection for unrecoverable failures, and cost/budget settlement.
"""

from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    Query,
)
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_fastapi.adapters.dependencies import get_pipeline

from hexaqueue_core.domain.collateral import CollateralBundle
from hexaqueue_core.domain.cqrs import (
    ClusterStatsReport,
    DeadLetterQueueReport,
    GetDeadLetterQueueQuery,
    GetFairShareTreeQuery,
    GetQueueStatsQuery,
    RegisterCollateralCommand,
    SettleBudgetCommand,
)
from hexaqueue_core.domain.explainability import FairShareTreeReport
from hexaqueue_server.adapters.api.auth import get_auth_context
from hexaqueue_server.adapters.api.common import _dispatch


def create_cluster_router() -> APIRouter:
    """Construct APIRouter for cluster statistics, fair-share, collateral, budget, and DLQ.

    Returns:
        APIRouter with endpoints for cluster queue statistics, DLQ, and accounting.
    """
    router = APIRouter()

    # 1. Fair-Share Tree
    @router.get(
        "/fairshare",
        response_model=FairShareTreeReport,
        summary="Get fair-share hierarchy tree",
    )
    def get_fairshare_tree(
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> FairShareTreeReport:
        user_id, is_elevated = auth
        qry = GetFairShareTreeQuery(requesting_user=user_id, is_admin=is_elevated)
        return _dispatch(pipeline, qry)

    # 2. Cluster Queue Statistics
    @router.get(
        "/stats",
        response_model=ClusterStatsReport,
        summary="Get aggregate cluster queue statistics",
    )
    def get_stats(
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> ClusterStatsReport:
        user_id, is_elevated = auth
        qry = GetQueueStatsQuery(user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, qry)

    # 3. Collateral Ingestion
    @router.post(
        "/collateral/upload",
        response_model=CollateralBundle,
        summary="Register and stage collateral artifact",
    )
    def register_collateral(
        cmd: RegisterCollateralCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> CollateralBundle:
        user_id, is_elevated = auth
        effective_cmd = RegisterCollateralCommand(
            name=cmd.name,
            version=cmd.version,
            checksum_sha256=cmd.checksum_sha256,
            size_bytes=cmd.size_bytes,
            tier=cmd.tier,
            kind=cmd.kind,
            target_path=cmd.target_path,
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pipeline, effective_cmd)

    # 4. Budget Settlement
    @router.post(
        "/budget/settle",
        response_model=dict[str, Any],
        summary="Settle project compute consumption",
    )
    def settle_budget(
        cmd: SettleBudgetCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> dict[str, Any]:
        user_id, is_elevated = auth
        effective_cmd = SettleBudgetCommand(
            project_id=cmd.project_id,
            amount_cents=cmd.amount_cents,
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pipeline, effective_cmd)

    # 5. Dead-Letter Queue (DLQ) Records
    @router.get(
        "/dlq",
        response_model=DeadLetterQueueReport,
        summary="Retrieve dead-lettered job failure records",
    )
    def get_dead_letters(
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
        limit: Annotated[int, Query(ge=1, le=1000)] = 50,
    ) -> DeadLetterQueueReport:
        user_id, is_elevated = auth
        qry = GetDeadLetterQueueQuery(limit=limit, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, qry)

    return router


__all__ = [
    "create_cluster_router",
]
