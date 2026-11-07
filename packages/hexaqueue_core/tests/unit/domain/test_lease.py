"""Unit tests for slice lease, task descriptor, and worker registration domain models.

Notes/Architectural Intent:
    Verifies domain invariants of the pull-based distributed slice scheduling protocol.
    Ensures side-effect-free assertions for CodeQL compliance.
"""

from datetime import UTC, datetime, timedelta

import pytest

from hexaqueue_core.domain.lease import (
    SliceLease,
    SliceLeaseState,
    SliceReportPayload,
    SliceTaskDescriptor,
    WorkerRegistration,
)


def test_worker_registration_valid() -> None:
    """Verify valid worker registration preserves hardware attributes."""
    reg = WorkerRegistration(
        worker_id="worker-oci-01",
        hostname="hq-worker-01",
        ip_address="10.0.2.15",
        ocpus=4,
        memory_mb=24576,
        labels={"pool": "a1-burst", "csp": "oci"},
    )
    worker_id = reg.worker_id
    ocpus = reg.ocpus
    ip_addr = reg.ip_address
    labels = reg.labels
    assert worker_id == "worker-oci-01"
    assert ocpus == 4
    assert ip_addr == "10.0.2.15"
    assert labels["pool"] == "a1-burst"


def test_worker_registration_blank_id_raises() -> None:
    """Verify blank worker_id raises ValueError."""
    with pytest.raises(ValueError, match="worker_id cannot be blank"):
        WorkerRegistration(worker_id="   ")


def test_slice_task_descriptor_initialization() -> None:
    """Verify SliceTaskDescriptor properties and default fields."""
    task = SliceTaskDescriptor(
        session_id="sess-alpha",
        slice_id="slice-0",
        slice_index=0,
        total_slices=4,
        test_nodeids=[
            "tests/unit/test_a.py::test_one",
            "tests/unit/test_b.py::test_two",
        ],
        collateral_id="col-xyz",
        collateral_download_url="https://objectstorage.us-phoenix-1.oraclecloud.com/p/get",
        coverage_upload_url="https://objectstorage.us-phoenix-1.oraclecloud.com/p/put",
        coverage_sources=["packages/demo/src"],
    )
    s_id = task.session_id
    slice_id = task.slice_id
    total = task.total_slices
    nodes = task.test_nodeids
    dn_url = task.collateral_download_url
    assert s_id == "sess-alpha"
    assert slice_id == "slice-0"
    assert total == 4
    assert len(nodes) == 2
    assert dn_url is not None


def test_slice_lease_lifecycle_and_renewal() -> None:
    """Verify lease lifecycle, expiration evaluation, and renewal."""
    task = SliceTaskDescriptor(
        session_id="sess-beta",
        slice_id="slice-1",
        slice_index=1,
        total_slices=2,
        test_nodeids=["tests/unit/test_c.py::test_three"],
    )
    now = datetime.now(UTC)
    lease = SliceLease(
        task=task,
        worker_id="worker-oci-02",
        expires_at=now + timedelta(seconds=30),
    )

    state = lease.state
    assert state == SliceLeaseState.LEASED
    is_exp = lease.is_expired
    assert is_exp is False

    # Renew lease
    renewed = lease.renew(extension_seconds=120)
    renewed_exp = renewed.expires_at
    assert renewed_exp > lease.expires_at

    # Expired lease
    expired_lease = SliceLease(
        task=task,
        worker_id="worker-oci-02",
        expires_at=now - timedelta(seconds=10),
    )
    expired_flag = expired_lease.is_expired
    assert expired_flag is True


def test_slice_report_payload_creation() -> None:
    """Verify SliceReportPayload fields and default outcome records."""
    report = SliceReportPayload(
        lease_id="lse-123",
        slice_id="slice-0",
        worker_id="worker-oci-01",
        exit_code=0,
        duration_seconds=1.45,
        outcomes=[{"nodeid": "test_one", "outcome": "passed", "duration": 0.05}],
        coverage_object_key="coverage/sess-alpha/slice-0.coverage",
    )
    lse_id = report.lease_id
    exit_val = report.exit_code
    dur = report.duration_seconds
    cov_key = report.coverage_object_key
    assert lse_id == "lse-123"
    assert exit_val == 0
    assert dur == 1.45
    assert cov_key == "coverage/sess-alpha/slice-0.coverage"
