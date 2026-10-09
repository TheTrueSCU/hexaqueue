"""Tests for LocalSchedulerControllerAdapter."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from hexastack_core.ports.notification import NotificationPort

from hexaqueue_core.adapters.coordination.in_memory import InMemoryLeaderElectionAdapter
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
from hexaqueue_core.domain.node import (
    ComputeNodeProfile,
    NodeHealthState,
    NodeProvisioningTier,
)
from hexaqueue_core.domain.notification import (
    NotificationPolicy,
    NotificationTrigger,
)
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.retry import JobRetryPolicy
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
    assert "**Completed Jobs:** 1" in second_call["body"]
    assert "**Failed Jobs:** 0" in second_call["body"]


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
    assert "**Completed Jobs:** 0" in run_call["body"]
    assert "**Failed Jobs:** 1" in run_call["body"]


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


@pytest.mark.asyncio
async def test_local_scheduler_controller_mode_and_governor_initialization() -> None:
    """Verify cluster execution mode and governor initialization behavior."""
    queue = InMemoryJobQueueAdapter()

    # 1. No governor and DEVELOPMENT mode -> stays DEVELOPMENT, governor is None
    c_dev = LocalSchedulerControllerAdapter(
        queue=queue,
        governor=None,
        mode=ExecutionMode.DEVELOPMENT,
    )
    assert c_dev._mode == ExecutionMode.DEVELOPMENT
    assert c_dev._governor is None

    # 2. Governor provided with DEVELOPMENT mode -> promoted to FREE_TIER
    gov = FreeTierGovernor()
    c_promoted = LocalSchedulerControllerAdapter(
        queue=queue,
        governor=gov,
        mode=ExecutionMode.DEVELOPMENT,
    )
    assert c_promoted._mode == ExecutionMode.FREE_TIER
    assert c_promoted._governor is gov


@pytest.mark.asyncio
async def test_local_scheduler_controller_production_mode_ignores_free_tier() -> None:
    """Verify PRODUCTION mode disables free tier evaluation even if governor is passed."""
    queue = InMemoryJobQueueAdapter()
    gov = FreeTierGovernor()
    controller = LocalSchedulerControllerAdapter(
        queue=queue,
        governor=gov,
        mode=ExecutionMode.PRODUCTION,
    )
    assert controller._mode == ExecutionMode.PRODUCTION

    run = RunSpec(id="run-prod", name="prod-run")
    j1 = JobSpec(
        id="j1-prod",
        run_id=run.id,
        name="job-prod",
        command="echo",
        resources=ResourceRequirements(gpus=4),  # Exceeds free tier limits
    )
    submission = RunSubmission(run_spec=run, jobs=[j1])

    # Direct check of _evaluate_free_tier_violations
    violations = controller._evaluate_free_tier_violations([j1])
    assert violations == {}

    report = await controller.submit_run(submission)
    assert report.free_tier_active is False
    assert report.burn_report is None
    assert report.state == RunState.RUNNING


@pytest.mark.asyncio
async def test_local_scheduler_controller_multi_hop_dag_failure_cascade() -> None:
    """Verify failure of root job cascades across multi-hop dependencies (A -> B -> C)."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    run = RunSpec(id="run-cascade", name="cascade-run")
    j_a = JobSpec(id="ja", run_id=run.id, name="job-a", command="echo a")
    j_b = JobSpec(id="jb", run_id=run.id, name="job-b", command="echo b")
    j_c = JobSpec(id="jc", run_id=run.id, name="job-c", command="echo c")

    submission = RunSubmission(
        run_spec=run,
        jobs=[j_c, j_b, j_a],
        dependencies={
            j_b.id: [j_a.id],
            j_c.id: [j_b.id],
        },
    )
    await controller.submit_run(submission)

    # Fail root job ja -> should cascade and mark jb and jc as BLOCKED
    await controller.update_job_outcome(j_a.id, TerminalOutcome.FAILED)

    job_b = await controller.get_job(j_b.id)
    assert job_b.state == JobState.BLOCKED
    assert job_b.status.reason == "Upstream prerequisite task failed"

    job_c = await controller.get_job(j_c.id)
    assert job_c.state == JobState.BLOCKED
    assert job_c.status.reason == "Upstream prerequisite task failed"


@pytest.mark.asyncio
async def test_local_scheduler_controller_release_non_held_job_noop() -> None:
    """Verify release_job on non-held jobs (prereq blocked or pending) is a no-op."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    run = RunSpec(id="run-release-noop", name="noop-run")
    j_a = JobSpec(id="ja-noop", run_id=run.id, name="job-a", command="echo a")
    j_b = JobSpec(id="jb-noop", run_id=run.id, name="job-b", command="echo b")

    submission = RunSubmission(
        run_spec=run,
        jobs=[j_a, j_b],
        dependencies={j_b.id: [j_a.id]},
    )
    await controller.submit_run(submission)

    # 1. Release pending job (ja) -> remains PENDING, not re-enqueued
    res_pending = await controller.release_job(j_a.id)
    assert res_pending.state == JobState.PENDING

    # 2. Fail ja so jb becomes BLOCKED with 'Upstream prerequisite task failed'
    await controller.update_job_outcome(j_a.id, TerminalOutcome.FAILED)
    jb_blocked = await controller.get_job(j_b.id)
    assert jb_blocked.state == JobState.BLOCKED
    assert jb_blocked.status.reason == "Upstream prerequisite task failed"

    # Releasing jb should NOT unblock it because reason != 'Administratively held'
    res_unheld = await controller.release_job(j_b.id)
    assert res_unheld.state == JobState.BLOCKED
    assert res_unheld.status.reason == "Upstream prerequisite task failed"


@pytest.mark.asyncio
async def test_local_scheduler_controller_notifications_job_timed_out() -> None:
    """Verify TIMED_OUT outcome increments failed_jobs in run notification."""
    mock_port = MagicMock(spec=NotificationPort)
    mock_port.notify.return_value = True
    dispatcher = NotificationDispatcher(notification_port=mock_port)

    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(
        queue=queue,
        notification_dispatcher=dispatcher,
    )

    policy = NotificationPolicy(
        targets=["slack://alerts"],
        triggers=NotificationTrigger.ERRORS,
    )

    run = RunSpec(
        id="run-timeout",
        name="timeout-run",
        notifications=[policy],
    )
    j1 = JobSpec(
        id="j1-timeout",
        run_id=run.id,
        name="job-timeout",
        command="sleep 100",
        notifications=[policy],
    )

    submission = RunSubmission(run_spec=run, jobs=[j1])
    await controller.submit_run(submission)
    mock_port.notify.reset_mock()

    await controller.update_job_outcome(
        j1.id, TerminalOutcome.TIMED_OUT, reason="Execution deadline exceeded"
    )
    call_cnt = mock_port.notify.call_count
    assert call_cnt == 2
    run_call = mock_port.notify.call_args_list[1][1]
    assert "**Failed Jobs:** 1" in run_call["body"]


@pytest.mark.asyncio
async def test_local_scheduler_controller_standby_leader_rejection() -> None:
    """Verify that standby controller rejects mutation requests until lease is acquired."""
    election = InMemoryLeaderElectionAdapter()
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(
        queue=queue,
        leader_election=election,
        controller_id="controller-standby",
    )

    run = RunSpec(id="run-standby-test", name="standby-test")
    j1 = JobSpec(id="j-standby", run_id=run.id, name="job-standby", command="echo")
    submission = RunSubmission(run_spec=run, jobs=[j1])

    # Standby cannot submit run
    with pytest.raises(HexaqueueError) as exc_info:
        await controller.submit_run(submission)
    err_msg = str(exc_info.value)
    assert "operating in standby mode" in err_msg

    # Standby cannot register node
    profile = ComputeNodeProfile(node_id="worker-01")
    with pytest.raises(HexaqueueError):
        await controller.register_node(profile)

    # Acquire leadership
    acq_ok = await election.acquire_leadership(
        "controller-standby", lease_duration_seconds=10.0
    )
    assert acq_ok is True

    # Now mutation succeeds
    rep = await controller.submit_run(submission)
    run_id = rep.run_id
    assert run_id == "run-standby-test"

    reg_res = await controller.register_node(profile)
    assert reg_res is None


@pytest.mark.asyncio
async def test_local_scheduler_controller_node_registration_and_heartbeat() -> None:
    """Verify compute node registration, pulse touching, and list retrieval."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    profile = ComputeNodeProfile(
        node_id="worker-node-alpha", tier=NodeProvisioningTier.STATIC
    )
    await controller.register_node(profile)

    nodes = await controller.list_nodes()
    node_count = len(nodes)
    assert node_count == 1
    node_id = nodes[0].node_id
    assert node_id == "worker-node-alpha"

    # Pulse heartbeat with cached hashes
    updated = await controller.heartbeat_node(
        worker_id="worker-node-alpha",
        active_job_ids=["job-x"],
        cached_collateral_hashes=["hash-123"],
    )
    assert "hash-123" in updated.cached_collateral_hashes
    assert "job-x" in updated.active_job_ids

    # Unregistered heartbeat raises HexaqueueError
    with pytest.raises(HexaqueueError):
        await controller.heartbeat_node(worker_id="unknown-node")


@pytest.mark.asyncio
async def test_local_scheduler_controller_evaluate_node_failures_and_retry() -> None:
    """Verify dead node detection re-enqueues in-flight jobs within max_retries."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    run = RunSpec(id="run-recover", name="recover-run")
    retry_policy = JobRetryPolicy(max_retries=2, initial_backoff_seconds=1.0)
    j1 = JobSpec(
        id="j-recover-1",
        run_id=run.id,
        name="job-recover",
        command="python",
        retry_policy=retry_policy,
        retry_count=0,
    )
    submission = RunSubmission(run_spec=run, jobs=[j1])
    await controller.submit_run(submission)

    # Dequeue and mark as running on worker-dead
    popped = await queue.dequeue()
    assert popped is not None

    # Register worker with old heartbeat (>30s ago)
    old_time = datetime.now(UTC) - timedelta(seconds=45)
    dead_profile = ComputeNodeProfile(
        node_id="worker-dead",
        tier=NodeProvisioningTier.STATIC,
        last_heartbeat_at=old_time,
    )
    await controller.register_node(dead_profile)

    # Assign job to worker-dead and set to RUNNING
    job_ref = await controller.get_job("j-recover-1")
    running_job = job_ref.model_copy(
        update={
            "assigned_worker_id": "worker-dead",
            "status": running_job.status.model_copy(update={"state": JobState.RUNNING})
            if (running_job := job_ref)
            else None,
        }
    )
    controller._jobs["j-recover-1"] = running_job

    # Evaluate node failures
    dead_nodes = await controller.evaluate_node_failures(
        timeout_unhealthy_seconds=15.0,
        timeout_dead_seconds=30.0,
    )
    dead_count = len(dead_nodes)
    assert dead_count == 1
    drained_state = dead_nodes[0].health_state
    assert drained_state == NodeHealthState.DRAINED

    # Check job was retried and re-enqueued
    requeued_job = await queue.dequeue()
    assert requeued_job is not None
    job_id = requeued_job.id
    assert job_id == "j-recover-1"
    retry_cnt = requeued_job.retry_count
    assert retry_cnt == 1
    assigned_worker = requeued_job.assigned_worker_id
    assert assigned_worker is None


@pytest.mark.asyncio
async def test_local_scheduler_controller_evaluate_node_failures_dlq_routing() -> None:
    """Verify dead node failure routes exhausted jobs to DLQ when max_retries exceeded."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    run = RunSpec(id="run-dlq", name="dlq-run")
    retry_policy = JobRetryPolicy(max_retries=1)
    j1 = JobSpec(
        id="j-dlq-1",
        run_id=run.id,
        name="job-dlq",
        command="python",
        retry_policy=retry_policy,
        retry_count=1,  # Exhausted!
    )
    submission = RunSubmission(run_spec=run, jobs=[j1])
    await controller.submit_run(submission)
    await queue.dequeue()

    old_time = datetime.now(UTC) - timedelta(seconds=50)
    dead_profile = ComputeNodeProfile(
        node_id="worker-crash",
        last_heartbeat_at=old_time,
    )
    await controller.register_node(dead_profile)

    job_ref = await controller.get_job("j-dlq-1")
    controller._jobs["j-dlq-1"] = job_ref.model_copy(
        update={
            "assigned_worker_id": "worker-crash",
            "status": job_ref.status.model_copy(update={"state": JobState.RUNNING}),
        }
    )

    # Evaluate failures
    await controller.evaluate_node_failures(
        timeout_unhealthy_seconds=15.0, timeout_dead_seconds=30.0
    )

    # Verify job moved to terminal FAILED
    failed_job = await controller.get_job("j-dlq-1")
    st = failed_job.state
    assert st == JobState.DONE
    out = failed_job.outcome
    assert out == TerminalOutcome.FAILED

    # Verify record in DLQ
    dlq_records = await controller.list_dead_letters()
    dlq_count = len(dlq_records)
    assert dlq_count == 1
    record = dlq_records[0]
    rec_job_id = record.job_id
    assert rec_job_id == "j-dlq-1"
    last_worker = record.last_worker_id
    assert last_worker == "worker-crash"


@pytest.mark.asyncio
async def test_local_scheduler_controller_schedule_placement() -> None:
    """Verify schedule_placement evaluates warm cache affinity and binds job to node."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    # Register cold and warm nodes
    node_cold = ComputeNodeProfile(
        node_id="node-cold", tier=NodeProvisioningTier.STATIC
    )
    node_warm = ComputeNodeProfile(
        node_id="node-warm",
        tier=NodeProvisioningTier.STATIC,
        cached_collateral_hashes=frozenset(["hash-dataset-1"]),
    )
    await controller.register_node(node_cold)
    await controller.register_node(node_warm)

    run = RunSpec(id="run-placement", name="placement-run")
    j1 = JobSpec(
        id="j-place-1",
        run_id=run.id,
        name="job-place",
        command="python",
        collateral_ids=["col-1"],
    )
    submission = RunSubmission(run_spec=run, jobs=[j1])
    await controller.submit_run(submission)

    decision = await controller.schedule_placement(
        job_id="j-place-1",
        collateral_hash_map={"col-1": "hash-dataset-1"},
    )
    sel_id = decision.selected_node_id
    assert sel_id == "node-warm"
    assert decision.warm_hits == 1

    # Verify job state updated to PROVISIONING and bound to node
    updated_job = await controller.get_job("j-place-1")
    worker = updated_job.assigned_worker_id
    assert worker == "node-warm"
    state = updated_job.state
    assert state == JobState.PROVISIONING
