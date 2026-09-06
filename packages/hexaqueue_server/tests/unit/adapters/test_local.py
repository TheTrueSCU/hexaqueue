"""Tests for LocalSchedulerControllerAdapter."""

import pytest

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.dag import DependencyCycleError
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import (
    JobState,
    RunOutcome,
    RunState,
    TerminalOutcome,
)
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.domain.models import RunSubmission


@pytest.mark.asyncio
async def test_local_scheduler_controller_dag_flow() -> None:
    """Verify DAG submission, readiness enqueueing, outcome progression, and completion."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    run = RunSpec(id="run-dag", name="dag-run")
    j1 = JobSpec(id="j1", run_id=run.id, name="job-1", command="echo", args=["1"])
    j2 = JobSpec(id="j2", run_id=run.id, name="job-2", command="echo", args=["2"])

    submission = RunSubmission(
        run_spec=run,
        jobs=[j1, j2],
        dependencies={j2.id: [j1.id]},
    )

    # 1. Submit run
    report = await controller.submit_run(submission)
    assert report.run_id == run.id
    assert report.total_jobs == 2
    assert report.pending_jobs == 2

    # Queue should only have j1 initially (j2 is blocked)
    queued_job = await queue.dequeue(timeout_seconds=0.1)
    assert queued_job is not None
    assert queued_job.id == j1.id

    # Dequeue again should timeout / be None because j2 is not ready
    assert await queue.dequeue(timeout_seconds=0.01) is None

    # 2. Complete j1
    await controller.update_job_outcome(j1.id, TerminalOutcome.COMPLETED)
    j1_status = await controller.get_job(j1.id)
    assert j1_status.state == JobState.DONE
    assert j1_status.outcome == TerminalOutcome.COMPLETED

    # Now j2 should be enqueued
    j2_queued = await queue.dequeue(timeout_seconds=0.1)
    assert j2_queued is not None
    assert j2_queued.id == j2.id

    # 3. Complete j2
    await controller.update_job_outcome(j2.id, TerminalOutcome.COMPLETED)

    # 4. Check run report
    final_report = await controller.get_run_status(run.id)
    assert final_report.state == RunState.DONE
    assert final_report.outcome == RunOutcome.SUCCEEDED
    assert final_report.completed_jobs == 2


@pytest.mark.asyncio
async def test_local_scheduler_controller_cycle_detection() -> None:
    """Verify cycle detection rejects invalid submissions."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    run = RunSpec(id="run-cycle", name="cyclic-run")
    j1 = JobSpec(id="j1", run_id=run.id, name="job-1", command="echo", args=["1"])
    j2 = JobSpec(id="j2", run_id=run.id, name="job-2", command="echo", args=["2"])

    submission = RunSubmission(
        run_spec=run,
        jobs=[j1, j2],
        dependencies={
            j2.id: [j1.id],
            j1.id: [j2.id],
        },
    )

    with pytest.raises(DependencyCycleError):
        await controller.submit_run(submission)


@pytest.mark.asyncio
async def test_local_scheduler_controller_duplicate_run() -> None:
    """Verify duplicate submission raises error."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    run = RunSpec(id="run-dup", name="dup-run")
    j1 = JobSpec(id="j1", run_id=run.id, name="job-1", command="echo", args=["1"])
    submission = RunSubmission(run_spec=run, jobs=[j1])

    await controller.submit_run(submission)
    with pytest.raises(HexaqueueError, match="is already registered"):
        await controller.submit_run(submission)


@pytest.mark.asyncio
async def test_local_scheduler_controller_not_found() -> None:
    """Verify not found errors."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    with pytest.raises(HexaqueueError, match="not found"):
        await controller.get_run_status("non-existent")

    with pytest.raises(HexaqueueError, match="not found"):
        await controller.get_job("non-existent")

    with pytest.raises(HexaqueueError, match="not found"):
        await controller.update_job_outcome("non-existent", TerminalOutcome.COMPLETED)

    with pytest.raises(HexaqueueError, match="not found"):
        await controller.cancel_run("non-existent")


@pytest.mark.asyncio
async def test_local_scheduler_controller_cancel_run() -> None:
    """Verify run cancellation cancels pending/uncompleted jobs."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    run = RunSpec(id="run-cancel", name="cancel-run")
    j1 = JobSpec(id="j1", run_id=run.id, name="job-1", command="echo", args=["1"])
    j2 = JobSpec(id="j2", run_id=run.id, name="job-2", command="echo", args=["2"])

    submission = RunSubmission(
        run_spec=run,
        jobs=[j1, j2],
        dependencies={j2.id: [j1.id]},
    )

    await controller.submit_run(submission)
    report = await controller.cancel_run(run.id)
    assert report.state == RunState.DONE
    assert report.outcome == RunOutcome.CANCELLED

    j1_spec = await controller.get_job(j1.id)
    assert j1_spec.state == JobState.DONE
    assert j1_spec.outcome == TerminalOutcome.CANCELLED


@pytest.mark.asyncio
async def test_local_scheduler_controller_failed_job() -> None:
    """Verify job failure handling."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    run = RunSpec(id="run-fail", name="fail-run")
    j1 = JobSpec(id="j1", run_id=run.id, name="job-1", command="echo", args=["1"])
    submission = RunSubmission(run_spec=run, jobs=[j1])

    await controller.submit_run(submission)
    await controller.update_job_outcome(
        j1.id, TerminalOutcome.FAILED, reason="Non-zero exit"
    )

    report = await controller.get_run_status(run.id)
    assert report.state == RunState.DONE
    assert report.outcome == RunOutcome.FAILED
    assert report.failed_jobs == 1


@pytest.mark.asyncio
async def test_controller_error_handling() -> None:
    """Verify controller raises errors on unknown job or run IDs."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    with pytest.raises(HexaqueueError, match="Run with ID 'unknown' not found"):
        await controller.get_run_status("unknown")

    with pytest.raises(HexaqueueError, match="Job with ID 'unknown' not found"):
        await controller.get_job("unknown")

    with pytest.raises(HexaqueueError, match="Job with ID 'unknown' not found"):
        await controller.update_job_outcome("unknown", TerminalOutcome.COMPLETED)
