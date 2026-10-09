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
    EvictExpiredCollateralCommand,
    FindCollateralByChecksumQuery,
    GetCollateralBundleQuery,
    GetCollateralDownloadUrlQuery,
    GetDeadLetterQueueQuery,
    GetFairShareTreeQuery,
    GetQueueStatsQuery,
    PinCollateralCommand,
    RegisterCollateralCommand,
    SettleBudgetCommand,
    UnpinCollateralCommand,
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

    # 3. Collateral Ingestion & Lifecycle
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
            ttl_seconds=cmd.ttl_seconds,
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pipeline, effective_cmd)

    @router.get(
        "/collateral/checksum/{sha256_checksum}",
        response_model=CollateralBundle | None,
        summary="Find approved collateral by SHA-256 CAS digest",
    )
    def find_collateral_by_checksum(
        sha256_checksum: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> CollateralBundle | None:
        user_id, is_elevated = auth
        qry = FindCollateralByChecksumQuery(
            sha256_checksum=sha256_checksum, user_id=user_id, elevate=is_elevated
        )
        return _dispatch(pipeline, qry)

    @router.get(
        "/collateral/{collateral_id}",
        response_model=CollateralBundle,
        summary="Retrieve collateral bundle metadata",
    )
    def get_collateral_bundle(
        collateral_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> CollateralBundle:
        user_id, is_elevated = auth
        qry = GetCollateralBundleQuery(
            collateral_id=collateral_id, user_id=user_id, elevate=is_elevated
        )
        return _dispatch(pipeline, qry)

    @router.get(
        "/collateral/{collateral_id}/download",
        response_model=dict[str, str],
        summary="Vend direct presigned download URL for approved collateral",
    )
    def get_collateral_download_url(
        collateral_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> dict[str, str]:
        user_id, is_elevated = auth
        qry = GetCollateralDownloadUrlQuery(
            collateral_id=collateral_id, user_id=user_id, elevate=is_elevated
        )
        url = _dispatch(pipeline, qry)
        return {"download_url": url}

    @router.post(
        "/collateral/{collateral_id}/pin",
        response_model=CollateralBundle,
        summary="Pin collateral bundle against eviction",
    )
    def pin_collateral(
        collateral_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> CollateralBundle:
        user_id, is_elevated = auth
        cmd = PinCollateralCommand(
            collateral_id=collateral_id, user_id=user_id, elevate=is_elevated
        )
        return _dispatch(pipeline, cmd)

    @router.post(
        "/collateral/{collateral_id}/unpin",
        response_model=CollateralBundle,
        summary="Unpin collateral bundle to permit reclamation",
    )
    def unpin_collateral(
        collateral_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> CollateralBundle:
        user_id, is_elevated = auth
        cmd = UnpinCollateralCommand(
            collateral_id=collateral_id, user_id=user_id, elevate=is_elevated
        )
        return _dispatch(pipeline, cmd)

    @router.post(
        "/collateral/evict",
        response_model=list[str],
        summary="Trigger garbage collection eviction for expired temporary collateral",
    )
    def evict_expired_collateral(
        cmd: EvictExpiredCollateralCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> list[str]:
        user_id, is_elevated = auth
        effective_cmd = EvictExpiredCollateralCommand(
            max_age_seconds=cmd.max_age_seconds,
            high_watermark_bytes=cmd.high_watermark_bytes,
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
