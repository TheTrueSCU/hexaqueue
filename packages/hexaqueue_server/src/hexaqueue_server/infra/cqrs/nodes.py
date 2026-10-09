"""CQRS handlers for compute node registration, heartbeats, telemetry, and bastion sessions.

Notes/Architectural Intent:
    Orchestrates cluster topology, heartbeat pulse recording, worker node profiling,
    and elevated administrative bastion shell session management.
"""

from hexaqueue_core.domain.cqrs import (
    CreateBastionSessionCommand,
    GetNodesQuery,
    HeartbeatNodeCommand,
    ListComputeNodesQuery,
    NodesReport,
    RegisterNodeCommand,
)
from hexaqueue_core.domain.exceptions import PermissionDeniedError
from hexaqueue_core.domain.node import ComputeNodeProfile
from hexaqueue_server.infra.cqrs.common import BaseCqrsService
from hexaqueue_worker.domain.pty import PtySessionInfo
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


class NodesCqrsMixin(BaseCqrsService):
    """Mixin implementing CQRS command and query handlers for compute nodes."""

    async def handle_create_bastion_session(
        self, cmd: CreateBastionSessionCommand
    ) -> PtySessionInfo:
        """Handle CreateBastionSessionCommand (requires explicit admin elevation).

        Args:
            cmd: Command payload.

        Returns:
            PtySessionInfo for bastion terminal.

        Raises:
            PermissionDeniedError: If not elevated.
        """
        if not cmd.elevate:
            msg = (
                f"Permission denied: Bastion shell access on node '{cmd.node_id}' "
                "requires explicit administrative elevation (--admin / elevate=true)."
            )
            raise PermissionDeniedError(msg)

        return PtySessionInfo(
            session_id=cmd.session_id,
            job_id=f"bastion-{cmd.node_id}",
            user_id=cmd.user_id,
            pid=54321,
            is_active=True,
        )

    async def handle_get_nodes(self, qry: GetNodesQuery) -> list[NodeTelemetryPulse]:
        """Handle GetNodesQuery.

        Args:
            qry: Query payload.

        Returns:
            List of registered NodeTelemetryPulse records.
        """
        if self.nodes:
            return self.nodes
        pulse = NodeTelemetryPulse(
            worker_id="node-local-01",
            cpu_utilization_pct=15.5,
            memory_total_mb=64 * 1024,
            memory_used_mb=16 * 1024,
            scratch_total_mb=500 * 1024,
            scratch_used_mb=50 * 1024,
            active_jobs=0,
            gpu_metrics=[],
        )
        return [pulse]

    async def handle_register_node(self, cmd: RegisterNodeCommand) -> None:
        """Handle RegisterNodeCommand.

        Args:
            cmd: Command payload.
        """
        await self.controller.register_node(cmd.profile)

    async def handle_heartbeat_node(
        self, cmd: HeartbeatNodeCommand
    ) -> ComputeNodeProfile:
        """Handle HeartbeatNodeCommand.

        Args:
            cmd: Command payload.

        Returns:
            Updated ComputeNodeProfile.
        """
        return await self.controller.heartbeat_node(
            worker_id=cmd.worker_id,
            active_job_ids=cmd.active_job_ids,
            cached_collateral_hashes=cmd.cached_collateral_hashes,
        )

    async def handle_list_compute_nodes(
        self, qry: ListComputeNodesQuery
    ) -> NodesReport:
        """Handle ListComputeNodesQuery.

        Args:
            qry: Query payload.

        Returns:
            NodesReport detailing registered compute worker nodes.
        """
        nodes = await self.controller.list_nodes()
        return NodesReport(nodes=nodes, total_nodes=len(nodes))


__all__ = [
    "NodesCqrsMixin",
]
