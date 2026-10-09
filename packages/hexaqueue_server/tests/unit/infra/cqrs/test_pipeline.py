"""Unit tests for create_hexaqueue_execution_pipeline factory."""

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.cqrs import GetQueueStatsQuery
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.infra.cqrs.pipeline import create_hexaqueue_execution_pipeline


def test_create_hexaqueue_execution_pipeline_assembly() -> None:
    """Verify execution pipeline constructs with all command and query registrations."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)

    assert pipeline is not None
    stats = pipeline.execute(GetQueueStatsQuery())
    assert stats.total_jobs == 0
