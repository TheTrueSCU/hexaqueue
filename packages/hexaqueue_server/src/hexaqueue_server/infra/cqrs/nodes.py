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
from hexaqueue_core.domain.node import (
    ComputeNodeProfile,
    NodeHealthState,
    NodeProvisioningTier,
)
from hexaqueue_core.ports.resources import NodeCapacity
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
            List of registered NodeTelemetryPulse records, merging static nodes
            and active pull-leased burst workers from SliceLeaseCoordinator.
        """
        if self.nodes:
            return self.nodes

        pulses: dict[str, NodeTelemetryPulse] = {}
        for node in await self.controller.list_nodes():
            total_ram = node.capacity.total_ram_mb if node.capacity else 64 * 1024
            avail_ram = node.capacity.available_ram_mb if node.capacity else total_ram
            pulses[node.node_id] = NodeTelemetryPulse(
                worker_id=node.node_id,
                cpu_utilization_pct=0.0,
                memory_total_mb=total_ram,
                memory_used_mb=max(0, total_ram - avail_ram),
                scratch_total_mb=500 * 1024,
                scratch_used_mb=0,
                active_jobs=len(node.active_job_ids),
                gpu_metrics=[],
                timestamp=node.last_heartbeat_at,
            )

        coord = getattr(self.controller, "_lease_coordinator", None)
        if coord is not None and hasattr(coord, "list_active_workers"):
            for reg, active_leases, last_seen in coord.list_active_workers():
                if reg.worker_id not in pulses:
                    telem = (
                        coord.get_worker_telemetry(reg.worker_id)
                        if hasattr(coord, "get_worker_telemetry")
                        else {}
                    )
                    pulses[reg.worker_id] = NodeTelemetryPulse(
                        worker_id=reg.worker_id,
                        cpu_utilization_pct=float(
                            telem.get("cpu_utilization_pct", 0.0)
                        ),
                        memory_total_mb=int(
                            telem.get("memory_total_mb", reg.memory_mb)
                        ),
                        memory_used_mb=int(telem.get("memory_used_mb", 0)),
                        scratch_total_mb=int(telem.get("scratch_total_mb", 0)),
                        scratch_used_mb=int(telem.get("scratch_used_mb", 0)),
                        active_jobs=active_leases,
                        gpu_metrics=[],
                        timestamp=last_seen,
                    )

        if pulses:
            return list(pulses.values())

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

        Raises:
            PermissionDeniedError: If unauthorized non-worker caller attempts registration without elevation.
        """
        is_worker = cmd.user_id.startswith("worker") or cmd.user_id in (
            cmd.profile.node_id,
            "system",
        )
        if not cmd.elevate and not is_worker:
            msg = (
                f"Permission denied: Registration of node '{cmd.profile.node_id}' "
                "requires worker credentials or explicit administrative elevation."
            )
            raise PermissionDeniedError(msg)

        await self.controller.register_node(cmd.profile)

    async def handle_heartbeat_node(
        self, cmd: HeartbeatNodeCommand
    ) -> ComputeNodeProfile:
        """Handle HeartbeatNodeCommand.

        Args:
            cmd: Command payload.

        Returns:
            Updated ComputeNodeProfile.

        Raises:
            PermissionDeniedError: If unauthorized caller attempts to spoof worker heartbeat.
        """
        is_worker = cmd.user_id.startswith("worker") or cmd.user_id in (
            cmd.worker_id,
            "system",
        )
        if not cmd.elevate and not is_worker:
            msg = (
                f"Permission denied: Emitting heartbeat for node '{cmd.worker_id}' "
                "requires worker credentials or explicit administrative elevation."
            )
            raise PermissionDeniedError(msg)

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
            NodesReport detailing registered compute worker nodes, including
            ephemeral pull-leased burst workers from SliceLeaseCoordinator.
        """
        nodes = list(await self.controller.list_nodes())
        seen_ids = {n.node_id for n in nodes}

        coord = getattr(self.controller, "_lease_coordinator", None)
        if coord is not None and hasattr(coord, "list_active_workers"):
            for reg, active_leases, last_seen in coord.list_active_workers():
                if reg.worker_id in seen_ids:
                    continue
                provider = reg.labels.get("provider", "oci")
                tier = (
                    NodeProvisioningTier.EPHEMERAL
                    if "pool" in reg.labels or provider.lower() != "local"
                    else NodeProvisioningTier.STATIC
                )
                nodes.append(
                    ComputeNodeProfile(
                        node_id=reg.worker_id,
                        tier=tier,
                        health_state=NodeHealthState.HEALTHY,
                        provider=provider,
                        arch=reg.labels.get("arch", "arm64"),
                        capacity=NodeCapacity(
                            node_id=reg.worker_id,
                            total_cpus=reg.ocpus,
                            available_cpus=max(0, reg.ocpus - active_leases),
                            total_ram_mb=reg.memory_mb,
                            available_ram_mb=reg.memory_mb,
                        ),
                        last_heartbeat_at=last_seen,
                        registered_at=reg.registered_at,
                    )
                )
        return NodesReport(nodes=nodes, total_nodes=len(nodes))


__all__ = [
    "NodesCqrsMixin",
]
