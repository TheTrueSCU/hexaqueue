"""Tests for LocalSchedulerControllerAdapter."""

from unittest.mock import MagicMock

import pytest
from hexastack_core.ports.notification import NotificationPort

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.config import ExecutionMode
from hexaqueue_core.domain.dag import DependencyCycleError
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.freetier import (
    GCP_ALWAYS_FREE_PROFILE,
    LOCAL_FREE_TIER_PROFILE,
    FreeTierGovernor,
)
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
from hexaqueue_core.domain.resources import ResourceRequirements
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


@pytest.mark.asyncio
async def test_local_scheduler_controller_list_jobs() -> None:
    """Verify list_jobs retrieves all registered jobs."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    run = RunSpec(id="run-list", name="list-run")
    j1 = JobSpec(id="j1", run_id=run.id, name="job-1", command="echo", args=["1"])
    j2 = JobSpec(id="j2", run_id=run.id, name="job-2", command="echo", args=["2"])
    submission = RunSubmission(run_spec=run, jobs=[j1, j2])

    await controller.submit_run(submission)
    all_jobs = await controller.list_jobs()
    job_ids = {j.id for j in all_jobs}
    assert job_ids == {"j1", "j2"}


@pytest.mark.asyncio
async def test_local_scheduler_controller_free_tier_gpu_blocking() -> None:
    """Verify GPU requests are blocked with FREE_TIER_CAPACITY_EXCEEDED."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(
        queue=queue,
        mode=ExecutionMode.FREE_TIER,
    )

    run = RunSpec(id="run-free-gpu", name="free-gpu-run")
    j_gpu = JobSpec(
        id="j-gpu",
        run_id=run.id,
        name="gpu-training",
        command="torchrun",
        resources=ResourceRequirements(gpus=1),
    )
    submission = RunSubmission(run_spec=run, jobs=[j_gpu])

    report = await controller.submit_run(submission)
    assert report.state == RunState.BLOCKED
    assert report.failed_jobs == 1
    assert report.free_tier_active is True
    assert report.burn_report is not None

    stored_job = await controller.get_job(j_gpu.id)
    assert stored_job.state == JobState.BLOCKED
    assert stored_job.outcome is None
    assert stored_job.status.reason is not None
    assert "FREE_TIER_CAPACITY_EXCEEDED" in stored_job.status.reason
    assert "strictly allows 0 GPUs" in stored_job.status.reason

    dequeued = await queue.dequeue(timeout_seconds=0.05)
    assert dequeued is None


@pytest.mark.asyncio
async def test_local_scheduler_controller_free_tier_region_and_cpu_blocking() -> None:
    """Verify invalid region and CPU caps are blocked, causing downstream cascading blocks."""
    queue = InMemoryJobQueueAdapter()
    governor = FreeTierGovernor(profile=GCP_ALWAYS_FREE_PROFILE)
    controller = LocalSchedulerControllerAdapter(
        queue=queue,
        governor=governor,
    )

    run = RunSpec(id="run-gcp-free", name="gcp-free-run")
    j1_bad_region = JobSpec(
        id="j1-region",
        run_id=run.id,
        name="job-bad-region",
        command="echo",
        tags=["region:eu-west-1"],
    )
    j2_bad_cpu = JobSpec(
        id="j2-cpu",
        run_id=run.id,
        name="job-bad-cpu",
        command="echo",
        resources=ResourceRequirements(cpus=8),
    )
    j3_dependent = JobSpec(
        id="j3-downstream",
        run_id=run.id,
        name="job-downstream",
        command="echo",
        tags=["region:us-central1"],
    )

    submission = RunSubmission(
        run_spec=run,
        jobs=[j1_bad_region, j2_bad_cpu, j3_dependent],
        dependencies={j3_dependent.id: [j1_bad_region.id]},
    )

    report = await controller.submit_run(submission)
    assert report.state == RunState.BLOCKED
    assert report.failed_jobs == 3
    assert report.free_tier_active is True

    stored_j1 = await controller.get_job(j1_bad_region.id)
    assert stored_j1.state == JobState.BLOCKED
    assert stored_j1.status.reason is not None
    assert "is not eligible for free-tier execution" in stored_j1.status.reason

    stored_j2 = await controller.get_job(j2_bad_cpu.id)
    assert stored_j2.state == JobState.BLOCKED
    assert stored_j2.status.reason is not None
    assert "exceeding Google Cloud (GCP) Always Free" in stored_j2.status.reason

    stored_j3 = await controller.get_job(j3_dependent.id)
    assert stored_j3.state == JobState.BLOCKED
    assert stored_j3.status.reason is not None
    assert "Upstream prerequisite task failed" in stored_j3.status.reason


@pytest.mark.asyncio
async def test_local_scheduler_controller_free_tier_burn_report() -> None:
    """Verify burn meter metrics report active allocations under Free-Tier Mode."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(
        queue=queue,
        mode=ExecutionMode.FREE_TIER,
    )

    run = RunSpec(id="run-valid-free", name="valid-free-run")
    j1 = JobSpec(
        id="j1-valid",
        run_id=run.id,
        name="job-valid",
        command="echo",
        resources=ResourceRequirements(cpus=1, ram_mb=1024),
    )
    submission = RunSubmission(run_spec=run, jobs=[j1])

    report = await controller.submit_run(submission)
    assert report.free_tier_active is True
    assert report.burn_report is not None
    burn = report.burn_report
    assert burn.allocated_cpus == 1
    assert burn.allocated_ram_mb == 1024
    assert burn.is_throttled is False
    assert burn.profile_name == LOCAL_FREE_TIER_PROFILE.name


@pytest.mark.asyncio
async def test_local_scheduler_controller_hold_and_release_job() -> None:
    """Verify hold_job blocks pending job and release_job enqueues it back."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    run = RunSpec(id="run-hold", name="hold-run")
    j1 = JobSpec(id="j1-hold", run_id=run.id, name="job-hold", command="echo")
    submission = RunSubmission(run_spec=run, jobs=[j1])
    await controller.submit_run(submission)

    # Hold job
    held = await controller.hold_job(j1.id)
    res_held_state = held.state
    assert res_held_state == JobState.BLOCKED

    # Re-holding already blocked job should return current spec
    reheld = await controller.hold_job(j1.id)
    res_reheld_state = reheld.state
    assert res_reheld_state == JobState.BLOCKED

    # Release job
    released = await controller.release_job(j1.id)
    res_rel_state = released.state
    assert res_rel_state == JobState.PENDING

    # Release again
    re_rel = await controller.release_job(j1.id)
    res_re_rel_state = re_rel.state
    assert res_re_rel_state == JobState.PENDING


@pytest.mark.asyncio
async def test_local_scheduler_controller_cancel_job() -> None:
    """Verify cancel_job sets CANCELLED outcome and removes job from queue."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    run = RunSpec(id="run-cancel", name="cancel-run")
    j1 = JobSpec(id="j1-cancel", run_id=run.id, name="job-cancel", command="echo")
    submission = RunSubmission(run_spec=run, jobs=[j1])
    await controller.submit_run(submission)

    cancelled = await controller.cancel_job(j1.id)
    res_state = cancelled.state
    res_outcome = cancelled.outcome
    assert res_state == JobState.DONE
    assert res_outcome == TerminalOutcome.CANCELLED

    # Cancelling non-existent job raises HexaqueueError
    with pytest.raises(HexaqueueError, match="not found"):
        await controller.cancel_job("non-existent")

    with pytest.raises(HexaqueueError, match="not found"):
        await controller.hold_job("non-existent")

    with pytest.raises(HexaqueueError, match="not found"):
        await controller.release_job("non-existent")
