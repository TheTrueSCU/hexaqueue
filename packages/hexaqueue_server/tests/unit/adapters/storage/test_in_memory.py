"""Unit tests for InMemorySchedulerStorageAdapter."""

from datetime import UTC, datetime

import pytest

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import RunOutcome, RunState
from hexaqueue_core.domain.node import ComputeNodeProfile
from hexaqueue_core.domain.telemetry import NodeTelemetryPulse
from hexaqueue_server.adapters.storage.in_memory import (
    InMemorySchedulerStorageAdapter,
)
from hexaqueue_server.domain.models import RunStatusReport


@pytest.mark.anyio
async def test_in_memory_storage_runs():
    """Verify run recording and retrieval in in-memory adapter."""
    adapter = InMemorySchedulerStorageAdapter()
    now = datetime.now(UTC)
    report1 = RunStatusReport(
        id="run-1",
        run_id="run-1",
        created_at=now,
        updated_at=now,
        status="RUNNING",
        state=RunState.RUNNING,
        total_jobs=2,
        completed_jobs=0,
        failed_jobs=0,
        pending_jobs=1,
        running_jobs=1,
    )
    report2 = RunStatusReport(
        id="run-2",
        run_id="run-2",
        created_at=now,
        updated_at=now,
        status="COMPLETED",
        state=RunState.DONE,
        outcome=RunOutcome.SUCCEEDED,
        total_jobs=1,
        completed_jobs=1,
        failed_jobs=0,
        pending_jobs=0,
        running_jobs=0,
    )

    await adapter.record_run(report1)
    await adapter.record_run(report2)

    retrieved = await adapter.get_run("run-1")
    assert retrieved is not None
    assert retrieved.id == "run-1"

    non_existent = await adapter.get_run("run-999")
    assert non_existent is None

    runs = await adapter.list_runs()
    assert len(runs) == 2


@pytest.mark.anyio
async def test_in_memory_storage_jobs():
    """Verify job recording and retrieval in in-memory adapter."""
    adapter = InMemorySchedulerStorageAdapter()
    job1 = JobSpec(id="job-1", run_id="run-1", name="step-1", command="echo 1")
    job2 = JobSpec(id="job-2", run_id="run-1", name="step-2", command="echo 2")
    job3 = JobSpec(id="job-3", run_id="run-2", name="step-3", command="echo 3")

    await adapter.record_job(job1)
    await adapter.record_job(job2)
    await adapter.record_job(job3)

    retrieved = await adapter.get_job("job-1")
    assert retrieved is not None
    assert retrieved.name == "step-1"

    run1_jobs = await adapter.list_jobs(run_id="run-1")
    assert len(run1_jobs) == 2

    all_jobs = await adapter.list_jobs()
    assert len(all_jobs) == 3


@pytest.mark.anyio
async def test_in_memory_storage_nodes():
    """Verify compute node profile storage."""
    adapter = InMemorySchedulerStorageAdapter()
    node = ComputeNodeProfile(node_id="worker-node-1")
    await adapter.record_node(node)

    retrieved = await adapter.get_node("worker-node-1")
    assert retrieved is not None
    assert retrieved.node_id == "worker-node-1"

    nodes = await adapter.list_nodes()
    assert len(nodes) == 1


@pytest.mark.anyio
async def test_in_memory_storage_telemetry():
    """Verify telemetry pulse recording and filtering."""
    adapter = InMemorySchedulerStorageAdapter()
    p1 = NodeTelemetryPulse(
        worker_id="w-1",
        cpu_utilization_pct=42.0,
        memory_used_mb=2048,
        memory_total_mb=8192,
        scratch_used_mb=100,
        scratch_total_mb=1000,
    )
    p2 = NodeTelemetryPulse(
        worker_id="w-2",
        cpu_utilization_pct=85.0,
        memory_used_mb=4096,
        memory_total_mb=8192,
        scratch_used_mb=200,
        scratch_total_mb=1000,
    )

    await adapter.record_telemetry_pulse(p1)
    await adapter.record_telemetry_pulse(p2)

    w1_pulses = await adapter.list_telemetry_pulses(worker_id="w-1")
    assert len(w1_pulses) == 1
    assert w1_pulses[0].worker_id == "w-1"

    all_pulses = await adapter.list_telemetry_pulses()
    assert len(all_pulses) == 2

    # Flush and close are no-ops
    await adapter.flush()
    await adapter.close()
