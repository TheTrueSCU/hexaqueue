"""CQRS handlers for cluster statistics, fair-share deficit, DLQ, and accounting.

Notes/Architectural Intent:
    Aggregates cluster capacity metrics, executes fair-share tree explainability,
    provides dead-letter queue inspection for unrecoverable failures, and confirms
    collateral registration and project budget settlement.
"""

import time
from typing import Any
from uuid import uuid4

from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralState,
)
from hexaqueue_core.domain.cqrs import (
    ClusterStatsReport,
    DeadLetterQueueReport,
    GetDeadLetterQueueQuery,
    GetFairShareTreeQuery,
    GetQueueStatsQuery,
    RegisterCollateralCommand,
    SettleBudgetCommand,
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
        checksum = cmd.checksum_sha256.zfill(64)
        return CollateralBundle(
            id=f"col-{uuid4().hex[:8]}",
            job_id="global",
            filename=cmd.name,
            size_bytes=cmd.size_bytes,
            sha256_checksum=checksum,
            tier=cmd.tier,
            kind=cmd.kind,
            state=CollateralState.REGISTERED,
            staging_uri=f"s3://staging/collateral/{cmd.name}",
        )

    async def handle_settle_budget(self, cmd: SettleBudgetCommand) -> dict[str, Any]:
        """Handle SettleBudgetCommand.

        Args:
            cmd: Command payload.

        Returns:
            Budget transaction confirmation dictionary.
        """
        return {
            "project_id": cmd.project_id,
            "settled_amount_cents": cmd.amount_cents,
            "status": "SETTLED",
            "actor": cmd.user_id,
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
