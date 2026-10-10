"""CQRS handlers for cluster statistics, fair-share deficit, DLQ, and accounting.

Notes/Architectural Intent:
    Aggregates cluster capacity metrics, executes fair-share tree explainability,
    provides dead-letter queue inspection for unrecoverable failures, and confirms
    collateral registration and project budget settlement.
"""

import time
from typing import Any

from hexaqueue_collateral.domain.models import IngestionRequest
from hexaqueue_core.domain.collateral import (
    CollateralBundle,
)
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
from hexaqueue_core.domain.explainability import (
    FairShareTreeReport,
    SchedulerExplainabilityEngine,
)
from hexaqueue_core.domain.lifecycle import JobState, TerminalOutcome
from hexaqueue_server.infra.cqrs.common import BaseCqrsService


class ClusterCqrsMixin(BaseCqrsService):
    """Mixin implementing CQRS command and query handlers for cluster-level operations."""

    async def handle_register_collateral(
        self, cmd: RegisterCollateralCommand
    ) -> CollateralBundle:
        """Handle RegisterCollateralCommand.

        Args:
            cmd: Command payload.

        Returns:
            Registered CollateralBundle.
        """
        req = IngestionRequest(
            filename=cmd.name,
            job_id=cmd.user_id,
            kind=cmd.kind,
            sha256_checksum=cmd.checksum_sha256.lower().strip().zfill(64),
            size_bytes=cmd.size_bytes,
            tier=cmd.tier,
            ttl_seconds=cmd.ttl_seconds,
        )
        desc = await self.collateral_service.register(req)
        return desc.bundle

    async def handle_get_collateral_bundle(
        self, qry: GetCollateralBundleQuery
    ) -> CollateralBundle:
        """Handle GetCollateralBundleQuery.

        Args:
            qry: Query payload.

        Returns:
            CollateralBundle metadata snapshot.
        """
        return await self.collateral_service.get_bundle(qry.collateral_id)

    async def handle_find_collateral_by_checksum(
        self, qry: FindCollateralByChecksumQuery
    ) -> CollateralBundle | None:
        """Handle FindCollateralByChecksumQuery.

        Args:
            qry: Query payload.

        Returns:
            Matching CollateralBundle if present in CAS active storage, or None.
        """
        return await self.collateral_service.find_by_checksum(qry.sha256_checksum)

    async def handle_get_collateral_download_url(
        self, qry: GetCollateralDownloadUrlQuery
    ) -> str:
        """Handle GetCollateralDownloadUrlQuery.

        Args:
            qry: Query payload.

        Returns:
            Preauthenticated direct download URL or verified file URI.
        """
        return await self.collateral_service.get_download_url(qry.collateral_id)

    async def handle_pin_collateral(
        self, cmd: PinCollateralCommand
    ) -> CollateralBundle:
        """Handle PinCollateralCommand.

        Args:
            cmd: Command payload.

        Returns:
            Updated CollateralBundle with incremented active pin count.
        """
        return await self.collateral_service.pin_bundle(cmd.collateral_id)

    async def handle_unpin_collateral(
        self, cmd: UnpinCollateralCommand
    ) -> CollateralBundle:
        """Handle UnpinCollateralCommand.

        Args:
            cmd: Command payload.

        Returns:
            Updated CollateralBundle with decremented active pin count.
        """
        return await self.collateral_service.unpin_bundle(cmd.collateral_id)

    async def handle_evict_expired_collateral(
        self, cmd: EvictExpiredCollateralCommand
    ) -> list[str]:
        """Handle EvictExpiredCollateralCommand.

        Args:
            cmd: Command payload.

        Returns:
            List of evicted collateral bundle IDs.
        """
        return await self.collateral_service.evict_expired(
            max_age_seconds=cmd.max_age_seconds,
            high_watermark_bytes=cmd.high_watermark_bytes,
        )

    async def handle_settle_budget(self, cmd: SettleBudgetCommand) -> dict[str, Any]:
        """Handle SettleBudgetCommand.

        Args:
            cmd: Command payload.

        Returns:
            Budget transaction confirmation dictionary.
        """
        if getattr(cmd, "reservation_id", "") and hasattr(self, "budget_port"):
            target_tenant = (
                None
                if getattr(cmd, "elevate", False)
                else (
                    getattr(cmd, "project_id", "")
                    or getattr(cmd, "user_id", "")
                    or None
                )
            )
            await self.budget_port.settle_budget(
                cmd.reservation_id,
                cmd.actual_credits,
                tenant_id=target_tenant,
            )
        return {
            "actor": cmd.user_id,
            "actual_credits": getattr(cmd, "actual_credits", 0.0),
            "project_id": cmd.project_id,
            "reservation_id": getattr(cmd, "reservation_id", ""),
            "settled_amount_cents": cmd.amount_cents,
            "status": "SETTLED",
        }

    async def handle_get_fairshare_tree(
        self, qry: GetFairShareTreeQuery
    ) -> FairShareTreeReport:
        """Handle GetFairShareTreeQuery.

        Args:
            qry: Query payload.

        Returns:
            FairShareTreeReport hierarchy.
        """
        engine = SchedulerExplainabilityEngine()
        return engine.explain_fairshare(current_timestamp=time.time())

    async def handle_get_queue_stats(
        self, qry: GetQueueStatsQuery
    ) -> ClusterStatsReport:
        """Handle GetQueueStatsQuery.

        Args:
            qry: Query payload.

        Returns:
            Aggregated ClusterStatsReport.
        """
        jobs = await self.controller.list_jobs()
        running = sum(1 for j in jobs if j.state == JobState.RUNNING)
        pending = sum(
            1
            for j in jobs
            if j.state in (JobState.PENDING, JobState.PROVISIONING, JobState.SUBMITTED)
        )
        blocked = sum(1 for j in jobs if j.state == JobState.BLOCKED)
        completed = sum(
            1
            for j in jobs
            if j.state == JobState.DONE and j.outcome == TerminalOutcome.COMPLETED
        )
        failed = sum(
            1
            for j in jobs
            if j.state == JobState.DONE
            and j.outcome
            in (
                TerminalOutcome.FAILED,
                TerminalOutcome.CANCELLED,
                TerminalOutcome.TIMED_OUT,
                TerminalOutcome.PREEMPTED,
            )
        )
        run_ids = {j.run_id for j in jobs}

        return ClusterStatsReport(
            total_runs=len(run_ids),
            total_jobs=len(jobs),
            running_jobs=running,
            pending_jobs=pending,
            blocked_jobs=blocked,
            completed_jobs=completed,
            failed_jobs=failed,
            active_workers=len(self.nodes) if self.nodes else 1,
        )

    async def handle_get_dead_letters(
        self, qry: GetDeadLetterQueueQuery
    ) -> DeadLetterQueueReport:
        """Handle GetDeadLetterQueueQuery.

        Args:
            qry: Query payload.

        Returns:
            DeadLetterQueueReport summarizing dead-lettered failure records.
        """
        records = await self.controller.list_dead_letters(limit=qry.limit)
        return DeadLetterQueueReport(records=records, total_count=len(records))


__all__ = [
    "ClusterCqrsMixin",
]
