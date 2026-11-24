"""Unit tests for Cluster Slice Lease Coordinator.

Notes/Architectural Intent:
    Verifies worker registration, pull leasing, heartbeat renewal, lease reclamation,
    and session completion aggregation. Assigns all assertion variables first for
    CodeQL compliance.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lease import (
    SliceReportPayload,
    WorkerRegistration,
)
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_server.adapters.api.test_runs import TestSliceDispatch
from hexaqueue_server.domain.lease_coordinator import SliceLeaseCoordinator


@pytest.mark.asyncio
async def test_worker_registration_and_heartbeat_tracking() -> None:
    """Verify worker registration and heartbeat pulse recording."""
    coord = SliceLeaseCoordinator()

    initial_workers = coord.active_worker_count
    assert initial_workers == 0

    reg = WorkerRegistration(
        worker_id="worker-01",
        hostname="hq-worker-01",
        ip_address="10.0.2.11",
        ocpus=2,
    )
    await coord.register_worker(reg)

    active_count = coord.active_worker_count
    assert active_count == 1

    # Heartbeat from registered worker
    hb_ok = await coord.record_heartbeat("worker-01")
    assert hb_ok is True

    # Heartbeat from unknown worker returns False
    hb_fail = await coord.record_heartbeat("worker-unknown")
    assert hb_fail is False


@pytest.mark.asyncio
async def test_enqueue_and_lease_slice_lifecycle() -> None:
    """Verify enqueuing session slices and leasing them to workers."""
    coord = SliceLeaseCoordinator(default_lease_ttl_seconds=60)

    slices = [
        TestSliceDispatch(
            slice_id="sl-1",
            slice_index=0,
            total_slices=2,
            test_nodeids=["test_a.py::test_1"],
        ),
        TestSliceDispatch(
            slice_id="sl-2",
            slice_index=1,
            total_slices=2,
            test_nodeids=["test_b.py::test_2"],
        ),
    ]

    event = await coord.enqueue_session_slices(
        session_id="sess-001",
        slices=slices,
        coverage_sources=["packages/core/src"],
    )
    is_done_init = event.is_set()
    assert is_done_init is False

    pending_init = coord.pending_count
    assert pending_init == 2

    # Worker leases first slice
    lease1 = await coord.lease_slice("worker-01", available_ocpus=2)
    assert lease1 is not None
    slice_id_1 = lease1.task.slice_id
    assert slice_id_1 == "sl-1"
    pending_after_1 = coord.pending_count
    active_after_1 = coord.active_lease_count
    assert pending_after_1 == 1
    assert active_after_1 == 1

    # Worker leases second slice
    lease2 = await coord.lease_slice("worker-02", available_ocpus=2)
    assert lease2 is not None
    slice_id_2 = lease2.task.slice_id
    assert slice_id_2 == "sl-2"
    pending_after_2 = coord.pending_count
    active_after_2 = coord.active_lease_count
    assert pending_after_2 == 0
    assert active_after_2 == 2

    # Third worker attempts lease on empty queue
    lease3 = await coord.lease_slice(
        "worker-03", available_ocpus=2, timeout_seconds=0.01
    )
    assert lease3 is None


@pytest.mark.asyncio
async def test_slice_reporting_and_session_completion() -> None:
    """Verify outcome reporting and automatic session event triggering."""
    coord = SliceLeaseCoordinator()

    slices = [
        TestSliceDispatch(
            slice_id="sl-a",
            slice_index=0,
            total_slices=1,
            test_nodeids=["test_suite.py::test_main"],
        )
    ]
    event = await coord.enqueue_session_slices("sess-alpha", slices)

    reg = WorkerRegistration(worker_id="worker-w1", ocpus=2)
    await coord.register_worker(reg)

    lease = await coord.lease_slice("worker-w1")
    assert lease is not None

    # Report completion
    report = SliceReportPayload(
        lease_id=lease.lease_id,
        slice_id="sl-a",
        worker_id="worker-w1",
        exit_code=0,
        duration_seconds=2.5,
        outcomes=[
            {"nodeid": "test_suite.py::test_main", "outcome": "passed", "duration": 2.5}
        ],
        coverage_object_key="coverage/sess-alpha/sl-a.coverage",
    )
    ok = await coord.report_slice_outcome(report)
    assert ok is True

    # Event triggered and report recorded
    is_done = event.is_set()
    assert is_done is True

    reports = await coord.get_session_reports("sess-alpha")
    report_count = len(reports)
    assert report_count == 1
    report_status = reports[0].outcomes[0].outcome
    assert report_status == "passed"


@pytest.mark.asyncio
async def test_reclaim_expired_leases_and_heartbeat_renewal() -> None:
    """Verify heartbeat extends lease and expired leases are reclaimed back to pending."""
    coord = SliceLeaseCoordinator(default_lease_ttl_seconds=1)

    slices = [
        TestSliceDispatch(
            slice_id="sl-reclaim",
            slice_index=0,
            total_slices=1,
            test_nodeids=["test_failover.py::test_drop"],
        )
    ]
    await coord.enqueue_session_slices("sess-failover", slices)

    reg = WorkerRegistration(worker_id="worker-drop", ocpus=1)
    await coord.register_worker(reg)

    lease = await coord.lease_slice("worker-drop")
    assert lease is not None

    # Renew lease via heartbeat
    renewed = await coord.record_heartbeat(
        "worker-drop", active_lease_ids=[lease.lease_id]
    )
    assert renewed is True

    # Manually expire the lease in coordinator internal state
    expired_lease = lease.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=5)}
    )
    async with coord._lock:
        coord._active_leases[lease.lease_id] = expired_lease

    # Reclaim expired leases
    reclaimed = await coord.reclaim_expired_leases()
    reclaimed_count = len(reclaimed)
    assert reclaimed_count == 1

    # Task is back in pending queue
    pending_count = coord.pending_count
    assert pending_count == 1

    # New worker leases the reclaimed slice
    new_lease = await coord.lease_slice("worker-recovery")
    assert new_lease is not None
    rec_slice_id = new_lease.task.slice_id
    assert rec_slice_id == "sl-reclaim"


@pytest.mark.asyncio
async def test_report_slice_missing_lease_returns_false() -> None:
    """Verify reporting against a nonexistent or revoked lease returns False."""
    coord = SliceLeaseCoordinator()
    report = SliceReportPayload(
        lease_id="lse-ghost",
        slice_id="sl-ghost",
        worker_id="worker-ghost",
        exit_code=1,
    )
    res = await coord.report_slice_outcome(report)
    assert res is False


@pytest.mark.asyncio
async def test_autoscaler_reconciliation_lifecycle() -> None:
    """Verify coordinator reconciles registered autoscaler on enqueue and completion."""
    mock_autoscaler = AsyncMock()
    mock_autoscaler.reconcile_pool = AsyncMock()

    coord = SliceLeaseCoordinator(
        autoscaler=mock_autoscaler,
        pool_id="pool-test",
    )
    has_auto = coord.has_autoscaler
    assert has_auto is True

    # Enqueuing slices triggers reconcile
    slice_item = TestSliceDispatch(
        slice_id="sl-auto",
        slice_index=0,
        total_slices=1,
        test_nodeids=["tests/test_a.py::test_1"],
    )
    _ev = await coord.enqueue_session_slices("sess-auto", [slice_item])
    await asyncio.sleep(0.05)

    call_count = mock_autoscaler.reconcile_pool.call_count
    assert call_count >= 1

    # Lease and report completion to trigger scale-down reconcile
    lease = await coord.lease_slice("worker-auto")
    assert lease is not None
    report = SliceReportPayload(
        lease_id=lease.lease_id,
        slice_id="sl-auto",
        worker_id="worker-auto",
        exit_code=0,
    )
    reported = await coord.report_slice_outcome(report)
    assert reported is True
    await asyncio.sleep(0.05)

    final_call_count = mock_autoscaler.reconcile_pool.call_count
    assert final_call_count >= 2


@pytest.mark.asyncio
async def test_enqueue_and_lease_job_spec() -> None:
    """Verify coordinator enqueues JobSpec, marks RUNNING on lease, and updates controller upon completion."""
    mock_ctrl = AsyncMock()
    mock_ctrl.mark_job_running = AsyncMock()
    mock_ctrl.mark_job_pending = AsyncMock()
    mock_ctrl.update_job_outcome = AsyncMock()

    coord = SliceLeaseCoordinator(controller=mock_ctrl)
    job = JobSpec(
        id="job-mut-001",
        run_id="run-mut-test",
        name="mutation-core",
        command="pytest",
        args=["--gremlins", "--gremlin-batch=0"],
        env={"PYTHONUNBUFFERED": "1", "HEXAQUEUE_CWD": "packages/core"},
    )
    await coord.enqueue_job(job)

    pending = coord.pending_count
    assert pending == 1

    lease = await coord.lease_slice("worker-oci-01")
    assert lease is not None
    running_called = mock_ctrl.mark_job_running.called
    assert running_called is True
    running_kwargs = mock_ctrl.mark_job_running.call_args[1]
    assert running_kwargs["job_id"] == "job-mut-001"
    assert running_kwargs["worker_id"] == "worker-oci-01"
    task = lease.task
    assert task.task_type == "job"
    assert task.slice_id == "job-mut-001"
    assert task.command == "pytest"
    assert task.args == ["--gremlins", "--gremlin-batch=0"]
    assert task.cwd == "packages/core"

    report = SliceReportPayload(
        lease_id=lease.lease_id,
        slice_id="job-mut-001",
        worker_id="worker-oci-01",
        exit_code=0,
        duration_seconds=12.5,
    )
    res = await coord.report_slice_outcome(report)
    assert res is True

    update_called = mock_ctrl.update_job_outcome.called
    assert update_called is True
    call_kwargs = mock_ctrl.update_job_outcome.call_args[1]
    assert call_kwargs["job_id"] == "job-mut-001"
    assert call_kwargs["outcome"] == TerminalOutcome.COMPLETED
    assert call_kwargs["walltime_seconds"] == 12.5


@pytest.mark.asyncio
async def test_reclaim_expired_job_lease_marks_pending() -> None:
    """Verify reclaiming an expired job lease transitions controller job back to PENDING."""
    mock_ctrl = AsyncMock()
    mock_ctrl.mark_job_running = AsyncMock()
    mock_ctrl.mark_job_pending = AsyncMock()

    coord = SliceLeaseCoordinator(controller=mock_ctrl, default_lease_ttl_seconds=1)
    job = JobSpec(
        id="job-exp-001",
        run_id="run-exp",
        name="exp-job",
        command="pytest",
    )
    await coord.enqueue_job(job)

    lease = await coord.lease_slice("worker-oci-02")
    assert lease is not None

    expired_lease = lease.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=10)}
    )
    async with coord._lock:
        coord._active_leases[lease.lease_id] = expired_lease

    reclaimed = await coord.reclaim_expired_leases()
    reclaimed_len = len(reclaimed)
    assert reclaimed_len == 1
    pending_called = mock_ctrl.mark_job_pending.called
    assert pending_called is True
    pending_kwargs = mock_ctrl.mark_job_pending.call_args[1]
    assert pending_kwargs["job_id"] == "job-exp-001"


@pytest.mark.asyncio
async def test_cancel_task_from_coordinator() -> None:
    """Verify coordinator cancels pending tasks."""
    coord = SliceLeaseCoordinator()
    job = JobSpec(
        id="job-cancel-001",
        run_id="run-cancel",
        name="cancel-job",
        command="echo",
    )
    await coord.enqueue_job(job)
    pending_before = coord.pending_count
    assert pending_before == 1

    cancelled = await coord.cancel_task("job-cancel-001")
    assert cancelled is True
    pending_after = coord.pending_count
    assert pending_after == 0


@pytest.mark.asyncio
async def test_lease_slice_auto_reclaims_expired_lease() -> None:
    """Verify lease_slice automatically reclaims expired leases before pulling."""
    coord = SliceLeaseCoordinator(default_lease_ttl_seconds=1)
    job = JobSpec(
        id="job-auto-reclaim-001",
        run_id="run-auto-reclaim",
        name="auto-reclaim-job",
        command="pytest",
    )
    await coord.enqueue_job(job)

    first_lease = await coord.lease_slice("worker-stale")
    assert first_lease is not None

    expired_lease = first_lease.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=5)}
    )
    async with coord._lock:
        coord._active_leases[first_lease.lease_id] = expired_lease

    recovered_lease = await coord.lease_slice("worker-fresh")
    assert recovered_lease is not None
    recovered_job_id = recovered_lease.task.slice_id
    assert recovered_job_id == "job-auto-reclaim-001"
    recovered_worker = recovered_lease.worker_id
    assert recovered_worker == "worker-fresh"


def test_format_failure_reason_includes_stderr_tail() -> None:
    """Verify _format_failure_reason appends stderr/stdout tail for failed jobs."""
    payload = SliceReportPayload(
        lease_id="lse-err-1",
        slice_id="sl-err-1",
        worker_id="worker-1",
        exit_code=1,
        outcomes=[
            {"nodeid": "pytest", "outcome": "failed", "stderr": "ImportError: boom"}
        ],
    )
    reason = SliceLeaseCoordinator._format_failure_reason(payload)
    assert reason is not None
    assert "Command failed with exit code 1" in reason
    assert "ImportError: boom" in reason


@pytest.mark.asyncio
async def test_capacity_readiness_and_session_leased_event() -> None:
    """Verify get_capacity_readiness states and get_session_leased_event trigger."""
    coord = SliceLeaseCoordinator()
    cap_idle = coord.get_capacity_readiness()
    assert cap_idle["capacity_state"] == "READY"
    assert cap_idle["ready"] is True

    slice_item = TestSliceDispatch(
        slice_id="sl-cap-1",
        slice_index=0,
        total_slices=1,
        test_nodeids=["tests/test_a.py::test_1"],
    )
    await coord.enqueue_session_slices("sess-cap", [slice_item])

    # With 0 workers and no autoscaler, pending slices make capacity DEGRADED
    cap_no_workers = coord.get_capacity_readiness()
    assert cap_no_workers["capacity_state"] == "DEGRADED"
    assert cap_no_workers["ready"] is False

    leased_ev = coord.get_session_leased_event("sess-cap")
    assert leased_ev is not None
    assert leased_ev.is_set() is False

    await coord.register_worker(WorkerRegistration(worker_id="w-cap-1", ocpus=2))
    cap_with_worker = coord.get_capacity_readiness()
    assert cap_with_worker["capacity_state"] == "READY"
    assert cap_with_worker["ready"] is True

    lease = await coord.lease_slice("w-cap-1")
    assert lease is not None
    assert leased_ev.is_set() is True


@pytest.mark.asyncio
async def test_cancel_task_evicts_active_leases_and_prevents_reclaim() -> None:
    """Verify cancel_task evicts both pending tasks and active leases and reconciles autoscaler."""
    mock_autoscaler = AsyncMock()
    mock_autoscaler.reconcile_pool = AsyncMock()
    coord = SliceLeaseCoordinator(
        default_lease_ttl_seconds=1,
        autoscaler=mock_autoscaler,
        pool_id="pool-cancel",
    )

    job1 = JobSpec(
        id="job-active-cancel-1",
        run_id="run-active-cancel",
        name="active-job",
        command="echo hello",
    )
    job2 = JobSpec(
        id="job-id-cancel-2",
        run_id="run-single-cancel",
        name="single-job",
        command="echo world",
    )
    await coord.enqueue_job(job1)
    await coord.enqueue_job(job2)

    lease1 = await coord.lease_slice("worker-1")
    lease2 = await coord.lease_slice("worker-2")
    assert lease1 is not None
    assert lease2 is not None

    # Expire both leases to ensure reclamation cannot resurrect cancelled jobs.
    past = datetime.now(UTC) - timedelta(seconds=10)
    async with coord._lock:
        coord._active_leases[lease1.lease_id] = lease1.model_copy(
            update={"expires_at": past}
        )
        coord._active_leases[lease2.lease_id] = lease2.model_copy(
            update={"expires_at": past}
        )

    # 1. Cancel by run_id (session_id)
    cancelled_by_run = await coord.cancel_task(job1.run_id)
    assert cancelled_by_run is True

    # 2. Cancel by individual job_id (slice_id)
    cancelled_by_job = await coord.cancel_task(job2.id)
    assert cancelled_by_job is True

    await asyncio.sleep(0.05)

    active_count = coord.active_lease_count
    pending_count = coord.pending_count
    assert active_count == 0
    assert pending_count == 0

    reclaimed = await coord.reclaim_expired_leases()
    reclaimed_len = len(reclaimed)
    assert reclaimed_len == 0

    late_report = SliceReportPayload(
        lease_id=lease1.lease_id,
        slice_id=job1.id,
        worker_id="worker-1",
        exit_code=0,
    )
    accepted = await coord.report_slice_outcome(late_report)
    assert accepted is False

    reconcile_calls = mock_autoscaler.reconcile_pool.call_count
    assert reconcile_calls >= 1

    # Also verify cancelling a session unblocks session completion event
    sess_event = await coord.enqueue_session_slices(
        "sess-cancel-unblock",
        [
            TestSliceDispatch(
                slice_id="sl-cancel-1",
                slice_index=0,
                total_slices=1,
                test_nodeids=["tests/test_x.py::test_1"],
            )
        ],
    )
    sess_cancelled = await coord.cancel_task("sess-cancel-unblock")
    assert sess_cancelled is True
    sess_done = sess_event.is_set()
    assert sess_done is True


@pytest.mark.asyncio
async def test_lease_slice_refreshes_collateral_download_url() -> None:
    """Verify lease_slice refreshes collateral PAR download URL right before handoff."""
    mock_collateral = MagicMock()
    mock_collateral.get_download_url = AsyncMock(
        side_effect=["https://par-stale", "https://par-fresh"]
    )
    coord = SliceLeaseCoordinator(collateral_service=mock_collateral)
    job = JobSpec(
        id="job-par-refresh",
        run_id="run-par-refresh",
        name="par-job",
        command="pytest",
        collateral_ids=["col-123"],
    )
    await coord.enqueue_job(job)

    lease = await coord.lease_slice("worker-par-1")
    assert lease is not None

    leased_url = lease.task.collateral_download_url
    assert leased_url == "https://par-fresh"

    stored_url = coord._active_leases[lease.lease_id].task.collateral_download_url
    assert stored_url == "https://par-fresh"


@pytest.mark.asyncio
async def test_lease_slice_falls_back_to_initial_collateral_url_on_refresh_error() -> (
    None
):
    """Verify transient refresh errors preserve the enqueue-time collateral PAR URL."""
    mock_collateral = MagicMock()
    mock_collateral.get_download_url = AsyncMock(
        side_effect=["https://par-initial", RuntimeError("oci transient")]
    )
    coord = SliceLeaseCoordinator(collateral_service=mock_collateral)
    job = JobSpec(
        id="job-par-fallback",
        run_id="run-par-fallback",
        name="par-fallback-job",
        command="pytest",
        collateral_ids=["col-456"],
    )
    await coord.enqueue_job(job)

    lease = await coord.lease_slice("worker-par-2")
    assert lease is not None

    leased_url = lease.task.collateral_download_url
    assert leased_url == "https://par-initial"


@pytest.mark.asyncio
async def test_cancel_task_records_only_cancelled_lease_ids() -> None:
    """Verify cancel_task records evicted active leases without flagging completed ones."""
    coord = SliceLeaseCoordinator()
    await coord.register_worker(
        WorkerRegistration(
            worker_id="worker-cancel-track",
            hostname="hq-cancel",
            ip_address="10.0.0.50",
            ocpus=2,
            memory_mb=4096,
        )
    )
    job_normal = JobSpec(
        id="job-normal",
        run_id="run-normal",
        name="normal-job",
        command="pytest",
    )
    job_cancelled = JobSpec(
        id="job-cancelled",
        run_id="run-cancelled",
        name="cancelled-job",
        command="pytest",
    )
    await coord.enqueue_job(job_normal)
    await coord.enqueue_job(job_cancelled)

    lease_normal = await coord.lease_slice("worker-cancel-track")
    lease_cancelled = await coord.lease_slice("worker-cancel-track")
    assert lease_normal is not None
    assert lease_cancelled is not None

    reported = await coord.report_slice_outcome(
        SliceReportPayload(
            lease_id=lease_normal.lease_id,
            slice_id=job_normal.id,
            worker_id="worker-cancel-track",
            exit_code=0,
            duration_seconds=0.1,
        )
    )
    assert reported is True

    was_cancelled = await coord.cancel_task("run-cancelled")
    assert was_cancelled is True

    cancelled_ids = coord.get_cancelled_lease_ids(
        [lease_normal.lease_id, lease_cancelled.lease_id]
    )
    assert cancelled_ids == [lease_cancelled.lease_id]
    is_recorded = lease_cancelled.lease_id in coord._cancelled_lease_ids
    assert is_recorded is True


@pytest.mark.asyncio
async def test_get_cancelled_lease_ids_handles_low_monotonic_uptime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify low monotonic uptime (< 3600s) does not flag non-cancelled leases."""
    monkeypatch.setattr(
        "hexaqueue_server.domain.lease_coordinator.time.monotonic",
        lambda: 100.0,
    )
    coord = SliceLeaseCoordinator()
    job_a = JobSpec(id="job-low-a", run_id="run-low-a", name="a", command="pytest")
    job_b = JobSpec(id="job-low-b", run_id="run-low-b", name="b", command="pytest")
    await coord.enqueue_job(job_a)
    await coord.enqueue_job(job_b)

    lease_a = await coord.lease_slice("worker-low-1")
    lease_b = await coord.lease_slice("worker-low-1")
    assert lease_a is not None
    assert lease_b is not None

    cancelled = await coord.cancel_task("run-low-a")
    assert cancelled is True

    active_cancelled = coord.get_cancelled_lease_ids(
        [lease_a.lease_id, lease_b.lease_id]
    )
    assert active_cancelled == [lease_a.lease_id]

    monkeypatch.setattr(
        "hexaqueue_server.domain.lease_coordinator.time.monotonic",
        lambda: 3701.0,
    )
    expired_cancelled = coord.get_cancelled_lease_ids(
        [lease_a.lease_id, lease_b.lease_id]
    )
    assert expired_cancelled == []


@pytest.mark.asyncio
async def test_periodic_reconciler_recovers_half_open_without_new_enqueue() -> None:
    """Verify background reconciler retries scale-up once OPEN cooldown expires (#219)."""
    from hexaqueue_core.domain.config import CspProvider
    from hexaqueue_core.domain.pool import InstancePoolState, PoolScaleResult
    from hexaqueue_server.domain.autoscaler import BudgetAwareInstancePoolAutoscaler

    gov = MagicMock()
    gov.check_pool_capacity = AsyncMock(return_value=True)
    gov.get_pool_state = AsyncMock(
        return_value=InstancePoolState(
            pool_id="pool-rec-1",
            provider=CspProvider.OCI,
            min_nodes=0,
            max_nodes=2,
            desired_nodes=0,
            current_nodes=0,
            ready_nodes=0,
        )
    )
    gov.scale_pool = AsyncMock(
        return_value=PoolScaleResult(
            pool_id="pool-rec-1",
            previous_nodes=0,
            target_nodes=1,
            success=True,
            message="ok",
        )
    )
    autoscaler = BudgetAwareInstancePoolAutoscaler(
        governors={"pool-rec-1": gov},
        circuit_cooldown_seconds=0.05,
    )
    autoscaler.trip_circuit("pool-rec-1", "transient capacity miss")

    coord = SliceLeaseCoordinator(autoscaler=autoscaler, pool_id="pool-rec-1")
    job = JobSpec(id="job-rec-1", run_id="run-rec-1", name="rec", command="pytest")
    await coord.enqueue_job(job)
    initial_scale_calls = gov.scale_pool.call_count
    assert initial_scale_calls == 0

    coord.start_reconciler(interval_seconds=0.02)
    try:
        for _ in range(15):
            if gov.scale_pool.call_count > 0:
                break
            await asyncio.sleep(0.02)
    finally:
        await coord.stop_reconciler()

    after_scale_calls = gov.scale_pool.call_count
    assert after_scale_calls >= 1


@pytest.mark.asyncio
async def test_periodic_reconciler_trips_stalled_scaling_pool_to_zero() -> None:
    """Verify background reconciler trips stalled SCALING pool and scales to 0 (#219)."""
    from hexaqueue_core.domain.config import CspProvider
    from hexaqueue_core.domain.pool import InstancePoolState, PoolScaleResult
    from hexaqueue_server.domain.autoscaler import BudgetAwareInstancePoolAutoscaler

    gov = MagicMock()
    gov.get_pool_state = AsyncMock(
        return_value=InstancePoolState(
            pool_id="pool-stall-1",
            provider=CspProvider.OCI,
            min_nodes=0,
            max_nodes=2,
            desired_nodes=1,
            current_nodes=0,
            ready_nodes=0,
        )
    )
    gov.scale_pool = AsyncMock(
        return_value=PoolScaleResult(
            pool_id="pool-stall-1",
            previous_nodes=1,
            target_nodes=0,
            success=True,
            message="scaled down",
        )
    )
    autoscaler = BudgetAwareInstancePoolAutoscaler(
        governors={"pool-stall-1": gov},
        scale_up_grace_seconds=0.03,
    )
    coord = SliceLeaseCoordinator(autoscaler=autoscaler, pool_id="pool-stall-1")
    autoscaler._scale_up_started_at["pool-stall-1"] = 0.0

    coord.start_reconciler(interval_seconds=0.02)
    try:
        for _ in range(15):
            if autoscaler.get_pool_circuit_status("pool-stall-1")["state"] == "OPEN":
                break
            await asyncio.sleep(0.02)
    finally:
        await coord.stop_reconciler()

    circuit_state = autoscaler.get_pool_circuit_status("pool-stall-1")["state"]
    assert circuit_state == "OPEN"
    scaled_targets = [c.args[0].target_nodes for c in gov.scale_pool.call_args_list]
    assert 0 in scaled_targets


def test_multi_pool_readiness_stays_closed_when_fallback_pool_healthy() -> None:
    """Verify aggregate readiness stays CLOSED when a fallback pool remains healthy."""
    from hexaqueue_server.domain.autoscaler import BudgetAwareInstancePoolAutoscaler

    autoscaler = BudgetAwareInstancePoolAutoscaler(
        governors={"pool-a1": MagicMock(), "pool-e5": MagicMock()}
    )
    autoscaler.trip_circuit("pool-a1", "Out of host capacity")

    coord = SliceLeaseCoordinator(
        autoscaler=autoscaler,
        pool_ids=["pool-a1", "pool-e5"],
    )
    readiness = coord.get_capacity_readiness()
    agg_state = readiness["pool_circuit"]["state"]
    pool_ids = readiness["pool_ids"]
    a1_state = readiness["pool_circuits"]["pool-a1"]["state"]
    e5_state = readiness["pool_circuits"]["pool-e5"]["state"]
    is_ready = readiness["ready"]
    assert agg_state == "CLOSED"
    assert pool_ids == ["pool-a1", "pool-e5"]
    assert a1_state == "OPEN"
    assert e5_state == "CLOSED"
    assert is_ready is True


@pytest.mark.asyncio
async def test_reconcile_autoscaler_coalesces_concurrent_triggers(
    coalescing_autoscaler: SimpleNamespace,
) -> None:
    """Verify concurrent _reconcile_autoscaler calls coalesce without overlapping CSP calls."""
    coord = SliceLeaseCoordinator(
        autoscaler=coalescing_autoscaler.autoscaler,
        pool_id="pool-coalesce-1",
    )
    t1 = asyncio.create_task(coord._reconcile_autoscaler())
    await asyncio.sleep(0.01)
    t2 = asyncio.create_task(coord._reconcile_autoscaler())
    t3 = asyncio.create_task(coord._reconcile_autoscaler())
    await asyncio.sleep(0.01)
    coalescing_autoscaler.release_first.set()
    await asyncio.gather(t1, t2, t3)

    max_in_flight = coalescing_autoscaler.stats["max_in_flight"]
    call_count = coalescing_autoscaler.stats["call_count"]
    assert max_in_flight == 1
    assert call_count == 2


@pytest.mark.asyncio
async def test_shutdown_evicts_leases_tracks_cancellations_and_notifies_controller() -> (
    None
):
    """Verify coordinator.shutdown() drains pending/leased tasks, records cancelled IDs, and notifies controller."""
    controller = MagicMock()
    controller.update_job_outcome = AsyncMock()
    coord = SliceLeaseCoordinator(controller=controller)
    await coord.register_worker(
        WorkerRegistration(
            worker_id="worker-shut-1",
            hostname="hq-shut",
            ip_address="10.0.0.9",
            ocpus=2,
            memory_mb=4096,
        )
    )
    job_active = JobSpec(
        id="job-shut-active",
        run_id="run-shut",
        name="shut-active",
        command="pytest",
    )
    job_pending = JobSpec(
        id="job-shut-pending",
        run_id="run-shut",
        name="shut-pending",
        command="pytest",
    )
    await coord.enqueue_job(job_active)
    await coord.enqueue_job(job_pending)
    lease = await coord.lease_slice("worker-shut-1")
    assert lease is not None

    has_active_before = coord.has_tracked_task("job-shut-active")
    has_pending_before = coord.has_tracked_task("job-shut-pending")
    assert has_active_before is True
    assert has_pending_before is True

    drained = await coord.shutdown(reason="Server shutting down")
    assert drained == 2
    assert coord.pending_count == 0
    assert coord.active_lease_count == 0
    cancelled_ids = coord.get_cancelled_lease_ids([lease.lease_id])
    assert cancelled_ids == [lease.lease_id]
    update_count = controller.update_job_outcome.await_count
    assert update_count == 2
