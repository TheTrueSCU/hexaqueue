"""Unit tests for Cluster Slice Lease Coordinator.

Notes/Architectural Intent:
    Verifies worker registration, pull leasing, heartbeat renewal, lease reclamation,
    and session completion aggregation. Assigns all assertion variables first for
    CodeQL compliance.
"""

from datetime import UTC, datetime, timedelta

import pytest

from hexaqueue_core.domain.lease import (
    SliceReportPayload,
    WorkerRegistration,
)
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
    import asyncio
    from unittest.mock import AsyncMock

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
