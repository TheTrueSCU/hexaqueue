"""Tests for LocalSchedulerControllerAdapter."""

from unittest.mock import MagicMock

import pytest
from hexastack_core.ports.notification import NotificationPort

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
from hexaqueue_core.domain.notification import (
    NotificationPolicy,
    NotificationTrigger,
)
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.infra.notification import NotificationDispatcher
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


@pytest.mark.asyncio
async def test_local_scheduler_controller_notifications_submit_and_complete() -> None:
    """Verify notification dispatcher triggers upon run submission, job completion, and run completion."""
    mock_port = MagicMock(spec=NotificationPort)
    mock_port.notify.return_value = True
    dispatcher = NotificationDispatcher(notification_port=mock_port)

    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(
        queue=queue,
        notification_dispatcher=dispatcher,
    )

    policy = NotificationPolicy(
        targets=["slack://deployments"],
        triggers=NotificationTrigger.SUBMITTED | NotificationTrigger.COMPLETED,
    )

    run = RunSpec(
        id="run-notif-1",
        name="notif-run",
        notifications=[policy],
    )
    j1 = JobSpec(
        id="j1",
        run_id=run.id,
        name="job-1",
        command="echo",
        args=["1"],
        notifications=[policy],
    )

    submission = RunSubmission(run_spec=run, jobs=[j1])

    # 1. Submit run -> triggers SUBMITTED on run
    res_submit = await controller.submit_run(submission)
    assert res_submit.run_id == run.id
    assert mock_port.notify.call_count == 1
    call_args_run = mock_port.notify.call_args[1]
    title_submit = call_args_run["title"]
    assert "SUBMITTED" in title_submit
    assert run.name in title_submit

    mock_port.notify.reset_mock()

    # 2. Complete j1 -> triggers COMPLETED on job AND COMPLETED on run
    await controller.update_job_outcome(j1.id, TerminalOutcome.COMPLETED)
    assert mock_port.notify.call_count == 2
    first_call = mock_port.notify.call_args_list[0][1]
    second_call = mock_port.notify.call_args_list[1][1]
    job_title = first_call["title"]
    run_title = second_call["title"]
    assert "COMPLETED" in job_title
    assert j1.name in job_title
    assert "COMPLETED" in run_title
    assert run.name in run_title


@pytest.mark.asyncio
async def test_local_scheduler_controller_notifications_job_failure() -> None:
    """Verify notification dispatcher triggers upon job failure and run failure."""
    mock_port = MagicMock(spec=NotificationPort)
    mock_port.notify.return_value = True
    dispatcher = NotificationDispatcher(notification_port=mock_port)

    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(
        queue=queue,
        notification_dispatcher=dispatcher,
    )

    policy = NotificationPolicy(
        targets=["pagerduty://service-1"],
        triggers=NotificationTrigger.ERRORS,
    )

    run = RunSpec(
        id="run-notif-fail",
        name="fail-run",
        notifications=[policy],
    )
    j1 = JobSpec(
        id="j1-fail",
        run_id=run.id,
        name="job-fail",
        command="exit 1",
        notifications=[policy],
    )

    submission = RunSubmission(run_spec=run, jobs=[j1])
    await controller.submit_run(submission)
    mock_port.notify.reset_mock()

    # Complete j1 with failure -> triggers FAILED on job and FAILED on run
    await controller.update_job_outcome(
        j1.id, TerminalOutcome.FAILED, reason="Non-zero exit status 1"
    )
    assert mock_port.notify.call_count == 2
    job_call = mock_port.notify.call_args_list[0][1]
    run_call = mock_port.notify.call_args_list[1][1]
    job_title = job_call["title"]
    run_title = run_call["title"]
    assert "FAILED" in job_title
    assert j1.name in job_title
    assert "FAILED" in run_title
    assert run.name in run_title


@pytest.mark.asyncio
async def test_local_scheduler_controller_notifications_cancel_run() -> None:
    """Verify notification dispatcher triggers CANCELLED events on cancel_run."""
    mock_port = MagicMock(spec=NotificationPort)
    mock_port.notify.return_value = True
    dispatcher = NotificationDispatcher(notification_port=mock_port)

    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(
        queue=queue,
        notification_dispatcher=dispatcher,
    )

    policy = NotificationPolicy(
        targets=["discord://webhook"],
        triggers=NotificationTrigger.CANCELLED,
    )

    run = RunSpec(
        id="run-notif-cancel",
        name="cancel-run",
        notifications=[policy],
    )
    j1 = JobSpec(
        id="j1-cancel",
        run_id=run.id,
        name="job-cancel",
        command="sleep 10",
        notifications=[policy],
    )

    submission = RunSubmission(run_spec=run, jobs=[j1])
    await controller.submit_run(submission)
    mock_port.notify.reset_mock()

    # Cancel run -> triggers CANCELLED on pending job j1 AND CANCELLED on run
    res_cancel = await controller.cancel_run(run.id)
    assert res_cancel.outcome == RunOutcome.CANCELLED
    assert mock_port.notify.call_count == 2
    job_call = mock_port.notify.call_args_list[0][1]
    run_call = mock_port.notify.call_args_list[1][1]
    job_title = job_call["title"]
    run_title = run_call["title"]
    assert "CANCELLED" in job_title
    assert j1.name in job_title
    assert "CANCELLED" in run_title
    assert run.name in run_title
