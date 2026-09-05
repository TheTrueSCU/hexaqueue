"""Unit tests for LocalSubprocessWorker adapter."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from hexaqueue_core.adapters.logging.in_memory import InMemoryLogStreamAdapter
from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.adapters.storage.in_memory import InMemoryStorageVolumeAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_worker.adapters.local import LocalSubprocessWorker
from hexaqueue_worker.domain.models import WorkerConfig


@pytest.mark.asyncio
async def test_worker_execute_job_success() -> None:
    """Verify single job execution, scratch lifecycle, and exit code 0."""
    queue = InMemoryJobQueueAdapter()
    storage = InMemoryStorageVolumeAdapter()
    log_port = InMemoryLogStreamAdapter()
    controller = AsyncMock()

    worker = LocalSubprocessWorker(
        queue=queue,
        controller=controller,
        storage=storage,
        log_port=log_port,
        config=WorkerConfig(worker_id="test-worker-1"),
    )

    job = JobSpec(
        id="job-1",
        run_id="run-1",
        name="echo-test",
        command="echo 'Hexaqueue Worker Running'",
        resources=ResourceRequirements(walltime_seconds=10, scratch_mb=50),
    )

    result = await worker.execute_job(job)
    assert result.exit_code == 0
    assert result.outcome == TerminalOutcome.COMPLETED

    # Verify controller notification
    controller.update_job_outcome.assert_awaited_once_with(
        job_id=job.id,
        outcome=TerminalOutcome.COMPLETED,
        reason=None,
    )

    # Verify scratch was allocated and cleaned up
    assert len(storage._allocations) == 0

    # Verify metrics
    metrics = await worker.get_metrics()
    assert metrics.worker_id == "test-worker-1"
    assert metrics.total_executed == 1
    assert metrics.total_completed == 1
    assert metrics.total_failed == 0
    assert metrics.active_jobs == 0


@pytest.mark.asyncio
async def test_worker_execute_job_failure() -> None:
    """Verify failed job exit code capture and status propagation."""
    queue = InMemoryJobQueueAdapter()
    storage = InMemoryStorageVolumeAdapter()
    controller = AsyncMock()

    worker = LocalSubprocessWorker(
        queue=queue,
        controller=controller,
        storage=storage,
    )

    job = JobSpec(
        id="job-fail",
        run_id="run-1",
        name="fail-test",
        command="sh -c 'echo \"failed task\" >&2; exit 7'",
        resources=ResourceRequirements(walltime_seconds=10),
    )

    result = await worker.execute_job(job)
    assert result.exit_code == 7
    assert result.outcome == TerminalOutcome.FAILED
    assert result.error_message is not None
    assert "failed task" in result.error_message

    controller.update_job_outcome.assert_awaited_once_with(
        job_id=job.id,
        outcome=TerminalOutcome.FAILED,
        reason=result.error_message,
    )

    metrics = await worker.get_metrics()
    assert metrics.total_executed == 1
    assert metrics.total_failed == 1
    assert metrics.total_completed == 0


@pytest.mark.asyncio
async def test_worker_poll_loop_e2e() -> None:
    """Verify background worker loop dequeuing, executing, and graceful shutdown."""
    queue = InMemoryJobQueueAdapter()
    storage = InMemoryStorageVolumeAdapter()
    controller = AsyncMock()

    worker = LocalSubprocessWorker(
        queue=queue,
        controller=controller,
        storage=storage,
        config=WorkerConfig(concurrency=2, poll_interval_seconds=0.01),
    )

    j1 = JobSpec(
        id="j1",
        run_id="run-1",
        name="j1",
        command="echo 1",
        resources=ResourceRequirements(walltime_seconds=10),
    )
    j2 = JobSpec(
        id="j2",
        run_id="run-1",
        name="j2",
        command="echo 2",
        resources=ResourceRequirements(walltime_seconds=10),
    )

    await queue.enqueue(j1)
    await queue.enqueue(j2)

    await worker.start()
    # Idempotent start
    await worker.start()

    # Allow poll loop to process both jobs
    for _ in range(50):
        metrics = await worker.get_metrics()
        if metrics.total_executed >= 2:
            break
        await asyncio.sleep(0.05)

    await worker.stop()
    # Idempotent stop
    await worker.stop()

    metrics = await worker.get_metrics()
    assert metrics.total_executed == 2
    assert metrics.total_completed == 2
    assert metrics.is_running is False
