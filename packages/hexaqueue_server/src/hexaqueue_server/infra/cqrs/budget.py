"""CQRS handlers for two-phase budget reservations, segment settlements, and cluster health.

Notes/Architectural Intent:
    Coordinates two-phase budget reservation holds, incremental preemption settlements,
    unspent credit releases, and cluster health telemetry aggregation. Enforces
    zero-leak credit conservation and non-double-counting invariants across the cluster.
"""

from typing import Any

from hexaqueue_core.domain.budget import ClusterHealthReport, TenantAccount
from hexaqueue_core.domain.cqrs import (
    GetClusterHealthQuery,
    GetTenantBalanceQuery,
    ReleaseBudgetCommand,
    ReserveBudgetCommand,
    SettleSegmentCommand,
)
from hexaqueue_server.infra.cqrs.common import BaseCqrsService


class BudgetCqrsMixin(BaseCqrsService):
    """Mixin implementing CQRS command and query handlers for budget and telemetry operations."""

    async def handle_reserve_budget(self, cmd: ReserveBudgetCommand) -> dict[str, Any]:
        """Handle ReserveBudgetCommand.

        Args:
            cmd: Command payload with tenant, job, and estimated credits.

        Returns:
            Dictionary containing reservation_id and reservation status.
        """
        reservation_id = await self.budget_port.reserve_budget(
            tenant_id=cmd.tenant_id,
            job_id=cmd.job_id,
            estimated_credits=cmd.estimated_credits,
        )
        return {
            "estimated_credits": cmd.estimated_credits,
            "job_id": cmd.job_id,
            "reservation_id": reservation_id,
            "status": "RESERVED",
            "tenant_id": cmd.tenant_id,
        }

    async def handle_settle_segment(self, cmd: SettleSegmentCommand) -> dict[str, Any]:
        """Handle SettleSegmentCommand.

        Args:
            cmd: Command payload with reservation hold and segment credits.

        Returns:
            Dictionary containing reservation_id, cumulative settled credits, and status.
        """
        cumulative = await self.budget_port.settle_segment(
            reservation_id=cmd.reservation_id,
            segment_credits=cmd.segment_credits,
        )
        return {
            "cumulative_credits": cumulative,
            "reservation_id": cmd.reservation_id,
            "segment_credits": cmd.segment_credits,
            "status": "SEGMENT_SETTLED",
        }

    async def handle_release_budget(self, cmd: ReleaseBudgetCommand) -> dict[str, Any]:
        """Handle ReleaseBudgetCommand.

        Args:
            cmd: Command payload with reservation hold identifier.

        Returns:
            Dictionary confirming reservation release.
        """
        await self.budget_port.release_budget(cmd.reservation_id)
        return {
            "reservation_id": cmd.reservation_id,
            "status": "RELEASED",
        }

    async def handle_get_tenant_balance(
        self, qry: GetTenantBalanceQuery
    ) -> TenantAccount:
        """Handle GetTenantBalanceQuery.

        Args:
            qry: Query payload with tenant account identifier.

        Returns:
            TenantAccount domain entity with balance and hold metrics.
        """
        return await self.budget_port.get_account(qry.tenant_id)

    async def handle_get_cluster_health(
        self, qry: GetClusterHealthQuery
    ) -> ClusterHealthReport:
        """Handle GetClusterHealthQuery.

        Args:
            qry: Query payload.

        Returns:
            ClusterHealthReport summarizing node health, capacities, and dead nodes.
        """
        return await self.cluster_monitor.get_cluster_health()


__all__ = [
    "BudgetCqrsMixin",
]
