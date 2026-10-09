"""Unit tests for HexaqueueCqrsService assembly and attributes."""

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.infra.cqrs.service import HexaqueueCqrsService


def test_hexaqueue_cqrs_service_initialization() -> None:
    """Verify HexaqueueCqrsService initializes and binds mixin capabilities."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    service = HexaqueueCqrsService(controller=controller)

    assert service.controller is controller
    assert service.log_store == {}
    assert service.nodes == []
    assert service.log_artifacts == {}
    assert service.storage_port is not None
