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
    CollateralTier,
)
from hexaqueue_core.domain.cqrs import (
    ClusterMetricsReport,
    ClusterStatsReport,
    DeadLetterQueueReport,
    DeleteCollateralCommand,
    EvictExpiredCollateralCommand,
    FindCollateralByChecksumQuery,
    GetClusterMetricsQuery,
    GetCollateralBundleQuery,
    GetCollateralDownloadUrlQuery,
    GetDeadLetterQueueQuery,
    GetFairShareTreeQuery,
    GetQueueStatsQuery,
    ListCollateralQuery,
    PinCollateralCommand,
    PromoteCollateralCommand,
    RegisterCollateralCommand,
    SettleBudgetCommand,
    UnpinCollateralCommand,
)
from hexaqueue_core.domain.exceptions import HexaqueueError, PermissionDeniedError
from hexaqueue_core.domain.explainability import (
    FairShareTreeReport,
    SchedulerExplainabilityEngine,
)
from hexaqueue_core.domain.fairshare import FairShareNode, FairShareTree
from hexaqueue_core.domain.lifecycle import JobState, TerminalOutcome
from hexaqueue_server.adapters.db.analytics import ColumnarAnalyticsAdapter
from hexaqueue_server.infra.cqrs.common import BaseCqrsService, _extract_job_owner


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
            owner=cmd.user_id or "default",
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

    async def handle_list_collateral(
        self, qry: ListCollateralQuery
    ) -> list[CollateralBundle]:
        """Handle ListCollateralQuery with RBAC owner scoping.

        Args:
            qry: Query payload containing caller identity and elevation flag.

        Returns:
            List of authorized CollateralBundle instances.

        Notes/Architectural Intent:
            Non-elevated callers see only bundles where ``owner == qry.user_id``.
            Elevated administrators see all collateral across owners.
        """
        if self.collateral_service is None:
            return []
        bundles = await self.collateral_service.list_bundles()
        if qry.elevate:
            return bundles
        return [bundle for bundle in bundles if bundle.owner == qry.user_id]

    async def handle_promote_collateral(
        self, cmd: PromoteCollateralCommand
    ) -> CollateralBundle:
        """Handle PromoteCollateralCommand.

        Args:
            cmd: Command payload specifying target collateral ID and elevation.

        Returns:
            Updated CollateralBundle promoted to PERMANENT tier.

        Raises:
            PermissionDeniedError: If caller lacks explicit admin elevation.
        """
        if not cmd.elevate:
            msg = (
                "Promoting collateral to PERMANENT requires explicit administrative "
                "elevation (--admin / elevate=true)."
            )
            raise PermissionDeniedError(msg)
        return await self.collateral_service.promote_bundle(cmd.collateral_id)

    async def handle_delete_collateral(self, cmd: DeleteCollateralCommand) -> str:
        """Handle DeleteCollateralCommand with RBAC and active-job guards.

        Args:
            cmd: Command payload specifying target collateral ID and caller identity.

        Returns:
            The deleted collateral bundle ID.

        Raises:
            PermissionDeniedError: If caller does not own the bundle or tries to
                delete PERMANENT collateral without admin elevation.
            HexaqueueError: If the bundle is pinned or referenced by active jobs.
        """
        bundle = await self.collateral_service.get_bundle(cmd.collateral_id)
        if not cmd.elevate:
            if bundle.owner != cmd.user_id:
                msg = (
                    f"Collateral {cmd.collateral_id} belongs to another owner; "
                    "explicit administrative elevation (--admin / elevate=true) is required."
                )
                raise PermissionDeniedError(msg)
            if bundle.tier == CollateralTier.PERMANENT:
                msg = (
                    "Deleting PERMANENT collateral requires explicit administrative "
                    "elevation (--admin / elevate=true)."
                )
                raise PermissionDeniedError(msg)

        if bundle.active_pin_count > 0:
            msg = (
                f"Cannot delete collateral {cmd.collateral_id}: "
                f"active_pin_count={bundle.active_pin_count}."
            )
            raise HexaqueueError(msg)

        jobs = await self.controller.list_jobs()
        referencing = [
            job.id
            for job in jobs
            if job.status.state is not JobState.DONE
            and cmd.collateral_id in job.collateral_ids
        ]
        if referencing:
            joined = ", ".join(referencing[:5])
            msg = (
                f"Cannot delete collateral {cmd.collateral_id}: "
                f"referenced by active job(s) {joined}."
            )
            raise HexaqueueError(msg)

        return await self.collateral_service.delete_bundle(cmd.collateral_id)

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
            FairShareTreeReport hierarchy populated with default and active job owners.
        """
        now = time.time()
        tree = FairShareTree()
        tree.add_node(FairShareNode(id="default", parent_id="root", shares=1.0))

        jobs = await self.controller.list_jobs()
        for job in jobs:
            owner = _extract_job_owner(job) or "default"
            if owner == "root":
                owner = "default"
            if tree.get_node(owner) is None:
                tree.add_node(FairShareNode(id=owner, parent_id="root", shares=1.0))
            cpus = max(
                float(getattr(getattr(job, "resources", None), "cpus", 1.0) or 1.0),
                1.0,
            )
            tree.record_usage(owner, cpus, now)

        engine = SchedulerExplainabilityEngine(fairshare_tree=tree)
        return engine.explain_fairshare(current_timestamp=now)

    async def handle_get_queue_stats(
        self, qry: GetQueueStatsQuery
    ) -> ClusterStatsReport:
        """Handle GetQueueStatsQuery.

        Args:
            qry: Query payload.

        Returns:
            Aggregated ClusterStatsReport.
        """
        get_stats = getattr(self.controller, "get_queue_stats", None)
        if callable(get_stats):
            return await get_stats()

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

        if self.nodes:
            active_workers = len(self.nodes)
        else:
            list_pulses = getattr(self.controller, "list_node_pulses", None)
            if callable(list_pulses):
                worker_ids = {p.worker_id for p in await list_pulses()}
            else:
                worker_ids = {n.node_id for n in await self.controller.list_nodes()}
            coord = getattr(self.controller, "_lease_coordinator", None)
            if coord is not None and hasattr(coord, "list_active_workers"):
                for reg, _, _ in coord.list_active_workers():
                    worker_ids.add(reg.worker_id)
            active_workers = len(worker_ids)

        return ClusterStatsReport(
            total_runs=len(run_ids),
            total_jobs=len(jobs),
            running_jobs=running,
            pending_jobs=pending,
            blocked_jobs=blocked,
            completed_jobs=completed,
            failed_jobs=failed,
            active_workers=active_workers,
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

    async def handle_get_cluster_metrics(
        self, qry: GetClusterMetricsQuery
    ) -> ClusterMetricsReport | bytes:
        """Handle GetClusterMetricsQuery using zero-copy columnar projections.

        Args:
            qry: Query payload specifying window and format.

        Returns:
            ClusterMetricsReport or binary columnar bytes.
        """
        jobs = await self.controller.list_jobs()
        nodes = self.nodes if self.nodes else []
        dlq_records = (
            await self.controller.list_dead_letters()
            if hasattr(self.controller, "list_dead_letters")
            else []
        )
        analytics = ColumnarAnalyticsAdapter()
        return analytics.project_cluster_metrics(
            qry, nodes=nodes, jobs=jobs, dlq_records=dlq_records
        )


__all__ = [
    "ClusterCqrsMixin",
]
