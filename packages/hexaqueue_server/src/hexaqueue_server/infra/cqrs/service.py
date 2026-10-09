"""Unified Hexaqueue CQRS application service orchestrator.

Notes/Architectural Intent:
    Assembles domain-specific CQRS mixins (runs, jobs, logs, nodes, cluster) into
    a single coherent application service, wiring controller, storage, and telemetry.
"""

from typing import Any

from hexaqueue_core.adapters.storage.presigned import InMemoryPresignedStorageAdapter
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_core.ports.storage import PresignedStoragePort
from hexaqueue_server.infra.cqrs.cluster import ClusterCqrsMixin
from hexaqueue_server.infra.cqrs.jobs import JobsCqrsMixin
from hexaqueue_server.infra.cqrs.logs import LogsCqrsMixin
from hexaqueue_server.infra.cqrs.nodes import NodesCqrsMixin
from hexaqueue_server.infra.cqrs.runs import RunsCqrsMixin
from hexaqueue_server.ports.controller import SchedulerControllerPort
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


class HexaqueueCqrsService(
    RunsCqrsMixin,
    JobsCqrsMixin,
    LogsCqrsMixin,
    NodesCqrsMixin,
    ClusterCqrsMixin,
):
    """Consolidated application service orchestrating Hexaqueue domain operations."""

    def __init__(
        self,
        controller: SchedulerControllerPort,
        log_store: dict[str, list[LogChunk]] | None = None,
        nodes: list[NodeTelemetryPulse] | None = None,
        storage_port: PresignedStoragePort | None = None,
    ) -> None:
        """Initialize the unified application service.

        Args:
            controller: Scheduler controller instance for lifecycle management.
            log_store: Optional in-memory store for historical log chunks.
            nodes: Optional list of registered worker node telemetry pulses.
            storage_port: Optional presigned storage port (defaults to InMemoryPresignedStorageAdapter).
        """
        self.controller = controller
        self.log_store = log_store if log_store is not None else {}
        self.nodes = nodes if nodes is not None else []
        self.storage_port = storage_port or InMemoryPresignedStorageAdapter()
        self.log_artifacts: dict[str, dict[str, Any]] = {}


__all__ = [
    "HexaqueueCqrsService",
]
