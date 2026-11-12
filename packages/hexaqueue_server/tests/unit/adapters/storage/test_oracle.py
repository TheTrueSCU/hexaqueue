"""Unit tests for OciAutonomousDatabaseStorageAdapter."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from hexastack_core.exceptions import MissingDependencyError
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import RunOutcome, RunState
from hexaqueue_core.domain.node import ComputeNodeProfile, NodeProvisioningTier
from hexaqueue_core.domain.telemetry import NodeTelemetryPulse
from hexaqueue_server.adapters.storage.oracle import (
    OciAutonomousDatabaseStorageAdapter,
)
from hexaqueue_server.domain.models import RunStatusReport


@pytest.fixture
def sync_engine():
    """Create in-memory SQLite engine for hermetic database tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    yield engine
    engine.dispose()


@pytest.mark.anyio
async def test_oracle_adapter_requires_dependency_on_oracle_url():
    """Verify require_dependency is invoked when oracle+oracledb URL is supplied."""
    with pytest.raises(MissingDependencyError, match="oracledb"):
        OciAutonomousDatabaseStorageAdapter(
            database_url="oracle+oracledb://user:pwd@adb_high"
        )


@pytest.mark.anyio
async def test_oracle_adapter_default_url_resolution(tmp_path):
    """Verify default and file-backed SQLite URL resolution."""
    adapter_default = OciAutonomousDatabaseStorageAdapter()
    await adapter_default.close()

    db_file = tmp_path / "test_adb.db"
    adapter_file = OciAutonomousDatabaseStorageAdapter(
        database_url=f"sqlite:///{db_file}"
    )
    await adapter_file.close()


@pytest.mark.anyio
async def test_oracle_adapter_run_lifecycle(sync_engine):
    """Verify run status persistence, hot caching, flush, and retrieval."""
    adapter = OciAutonomousDatabaseStorageAdapter(
        engine=sync_engine,
        flush_interval_seconds=0.05,
    )
    now = datetime.now(UTC)
    report = RunStatusReport(
        id="run-101",
        run_id="run-101",
        status="RUNNING",
        state=RunState.RUNNING,
        total_jobs=5,
        completed_jobs=1,
        failed_jobs=0,
        pending_jobs=3,
        running_jobs=1,
        created_at=now,
        updated_at=now,
    )

    await adapter.record_run(report)

    # Hot tier should return immediately
    hot_run = await adapter.get_run("run-101")
    assert hot_run is not None
    assert hot_run.id == "run-101"

    # Flush write-behind queue to durable storage
    await adapter.flush()

    # Clear hot cache to force database fetch
    adapter._hot_runs.clear()
    durable_run = await adapter.get_run("run-101")
    assert durable_run is not None
    assert durable_run.id == "run-101"
    assert durable_run.total_jobs == 5

    missing_run = await adapter.get_run("run-missing")
    assert missing_run is None

    # Update run
    report_updated = RunStatusReport(
        id="run-101",
        run_id="run-101",
        status="COMPLETED",
        state=RunState.DONE,
        outcome=RunOutcome.SUCCEEDED,
        total_jobs=5,
        completed_jobs=5,
        failed_jobs=0,
        pending_jobs=0,
        running_jobs=0,
        created_at=now,
        updated_at=now,
    )
    await adapter.record_run(report_updated)
    await adapter.flush()

    adapter._hot_runs.clear()
    runs = await adapter.list_runs()
    assert len(runs) == 1
    assert runs[0].status == "COMPLETED"

    await adapter.close()


@pytest.mark.anyio
async def test_oracle_adapter_job_lifecycle(sync_engine):
    """Verify job specification persistence, updates, and filtering."""
    adapter = OciAutonomousDatabaseStorageAdapter(
        engine=sync_engine,
        flush_interval_seconds=0.05,
    )
    job1 = JobSpec(id="job-1", run_id="run-A", name="step-1", command="echo 1")
    job2 = JobSpec(id="job-2", run_id="run-A", name="step-2", command="echo 2")
    job3 = JobSpec(id="job-3", run_id="run-B", name="step-3", command="echo 3")

    await adapter.record_job(job1)
    await adapter.record_job(job2)
    await adapter.record_job(job3)

    hot_job = await adapter.get_job("job-1")
    assert hot_job is not None

    await adapter.flush()

    # Update job1
    job1_updated = JobSpec(
        id="job-1", run_id="run-A", name="step-1-updated", command="echo 1"
    )
    await adapter.record_job(job1_updated)
    await adapter.flush()

    adapter._hot_jobs.clear()
    retrieved_job = await adapter.get_job("job-1")
    assert retrieved_job is not None
    assert retrieved_job.name == "step-1-updated"

    missing_job = await adapter.get_job("job-missing")
    assert missing_job is None

    run_a_jobs = await adapter.list_jobs(run_id="run-A")
    assert len(run_a_jobs) == 2

    all_jobs = await adapter.list_jobs()
    assert len(all_jobs) == 3

    await adapter.close()


@pytest.mark.anyio
async def test_oracle_adapter_node_lifecycle(sync_engine):
    """Verify compute worker node registration and listing."""
    adapter = OciAutonomousDatabaseStorageAdapter(
        engine=sync_engine,
        flush_interval_seconds=0.05,
    )
    node1 = ComputeNodeProfile(node_id="node-alpha", tier=NodeProvisioningTier.STATIC)
    node2 = ComputeNodeProfile(node_id="node-beta", tier=NodeProvisioningTier.EPHEMERAL)

    await adapter.record_node(node1)
    await adapter.record_node(node2)

    hot_node = await adapter.get_node("node-alpha")
    assert hot_node is not None

    await adapter.flush()

    # Update node1
    node1_updated = ComputeNodeProfile(
        node_id="node-alpha", tier=NodeProvisioningTier.EPHEMERAL
    )
    await adapter.record_node(node1_updated)
    await adapter.flush()

    adapter._hot_nodes.clear()
    retrieved_node = await adapter.get_node("node-alpha")
    assert retrieved_node is not None
    assert retrieved_node.tier == NodeProvisioningTier.EPHEMERAL

    missing_node = await adapter.get_node("node-missing")
    assert missing_node is None

    nodes = await adapter.list_nodes()
    assert len(nodes) == 2

    await adapter.close()


@pytest.mark.anyio
async def test_oracle_adapter_telemetry_pulses(sync_engine):
    """Verify telemetry pulse recording and filtering."""
    adapter = OciAutonomousDatabaseStorageAdapter(
        engine=sync_engine,
        flush_interval_seconds=0.05,
    )
    p1 = NodeTelemetryPulse(
        worker_id="worker-1",
        cpu_utilization_pct=45.0,
        memory_used_mb=2048,
        memory_total_mb=8192,
        scratch_used_mb=100,
        scratch_total_mb=1000,
    )
    p2 = NodeTelemetryPulse(
        worker_id="worker-2",
        cpu_utilization_pct=90.0,
        memory_used_mb=4096,
        memory_total_mb=8192,
        scratch_used_mb=200,
        scratch_total_mb=1000,
    )

    await adapter.record_telemetry_pulse(p1)
    await adapter.record_telemetry_pulse(p2)
    await adapter.flush()

    adapter._hot_telemetry.clear()
    w1_pulses = await adapter.list_telemetry_pulses(worker_id="worker-1")
    assert len(w1_pulses) == 1
    assert w1_pulses[0].worker_id == "worker-1"

    all_pulses = await adapter.list_telemetry_pulses()
    assert len(all_pulses) == 2

    await adapter.close()


@pytest.mark.anyio
async def test_oracle_adapter_queue_full_drain(sync_engine):
    """Verify queue full condition forces synchronous drain across all entity types."""
    adapter = OciAutonomousDatabaseStorageAdapter(
        engine=sync_engine,
        max_buffer_size=1,
        batch_size=1,
    )
    now = datetime.now(UTC)
    report1 = RunStatusReport(
        id="r-1",
        run_id="r-1",
        state=RunState.RUNNING,
        total_jobs=1,
        completed_jobs=0,
        failed_jobs=0,
        pending_jobs=1,
        running_jobs=0,
        created_at=now,
        updated_at=now,
    )
    report2 = RunStatusReport(
        id="r-2",
        run_id="r-2",
        state=RunState.RUNNING,
        total_jobs=1,
        completed_jobs=0,
        failed_jobs=0,
        pending_jobs=1,
        running_jobs=0,
        created_at=now,
        updated_at=now,
    )
    await adapter.record_run(report1)
    await adapter.record_run(report2)

    job1 = JobSpec(id="job-1", run_id="run-X", name="task-1", command="echo 1")
    job2 = JobSpec(id="job-2", run_id="run-X", name="task-2", command="echo 2")
    await adapter.record_job(job1)
    await adapter.record_job(job2)

    node1 = ComputeNodeProfile(node_id="n-1")
    node2 = ComputeNodeProfile(node_id="n-2")
    await adapter.record_node(node1)
    await adapter.record_node(node2)

    p1 = NodeTelemetryPulse(
        worker_id="w-1",
        memory_used_mb=100,
        memory_total_mb=1000,
        scratch_used_mb=100,
        scratch_total_mb=1000,
    )
    await adapter.record_telemetry_pulse(p1)
    await adapter.record_telemetry_pulse(p1)
    await adapter.flush()

    adapter._hot_jobs.clear()
    jobs = await adapter.list_jobs(run_id="run-X")
    assert len(jobs) == 2

    await adapter.close()


@pytest.mark.anyio
async def test_oracle_adapter_retry_exhaustion(sync_engine):
    """Verify retry logic raises HexaqueueError when database fails repeatedly."""
    adapter = OciAutonomousDatabaseStorageAdapter(
        engine=sync_engine,
        max_retries=2,
    )
    node = ComputeNodeProfile(node_id="node-fail")
    await adapter.record_node(node)

    with (
        patch.object(
            adapter,
            "_sync_persist_batch",
            side_effect=RuntimeError(
                "ORA-12514: TNS:listener does not currently know of service"
            ),
        ),
        pytest.raises(HexaqueueError, match="Failed to persist batch to ADB"),
    ):
        await adapter.flush()

    await adapter.close()
