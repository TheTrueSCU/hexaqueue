"""Shared fixtures for CQRS unit test suite."""

from collections.abc import Generator

import pytest
from hexastack_cqrs.infra.pipeline import ExecutionPipeline

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.infra.cqrs.pipeline import create_hexaqueue_execution_pipeline


@pytest.fixture
def hermetic_cqrs_pipeline() -> Generator[
    tuple[LocalSchedulerControllerAdapter, ExecutionPipeline]
]:
    """Hermetic fixture providing a clean controller and execution pipeline."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    log_store: dict[str, list[LogChunk]] = {
        "job-log-1": [
            LogChunk(
                job_id="job-log-1",
                stream="stdout",
                content="Starting worker process\n",
                offset=0,
            ),
            LogChunk(
                job_id="job-log-1",
                stream="stdout",
                content="Execution complete\n",
                offset=1,
            ),
        ]
    }
    pipeline = create_hexaqueue_execution_pipeline(
        controller=controller, log_store=log_store
    )
    yield controller, pipeline
