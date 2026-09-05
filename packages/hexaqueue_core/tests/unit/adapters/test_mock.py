"""Unit tests for in-memory and mock port adapters."""

import pytest
from hexaqueue_core.adapters.mock import (
    InMemoryJobQueueAdapter,
    InMemoryLogStreamAdapter,
    LocalComputeResourceAdapter,
    LocalDiskStorageVolumeAdapter,
    LocalSubprocessExecutionRuntimeAdapter,
    MockBudgetAccountingAdapter,
    NoOpSecurityQuarantineAdapter,
    ZeroCostRateModelAdapter,
)
from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralState,
    CollateralTier,
)
from hexaqueue_core.domain.exceptions import QuotaExceededError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.ports.logging import LogChunk


@pytest.mark.asyncio
async def test_in_memory_job_queue():
    """Verify FIFO queue ordering, dequeue, and peek operations."""
    queue = InMemoryJobQueueAdapter()
    assert await queue.size() == 0

    job_1 = JobSpec(
        id="job-1",
        run_id="run-1",
        name="job-first",
        command="echo first",
    )
    job_2 = JobSpec(
        id="job-2",
        run_id="run-1",
        name="job-second",
        command="echo second",
    )

    await queue.enqueue(job_1)
    await queue.enqueue(job_2)

    assert await queue.size() == 2
    peeked = await queue.peek(limit=5)
    assert len(peeked) == 2
    assert peeked[0].id == "job-1"

    dequeued_1 = await queue.dequeue()
    assert dequeued_1 is not None and dequeued_1.id == "job-1"

    dequeued_2 = await queue.dequeue()
    assert dequeued_2 is not None and dequeued_2.id == "job-2"

    assert await queue.dequeue() is None


@pytest.mark.asyncio
async def test_in_memory_job_queue_remove():
    """Verify job removal from queue."""
    queue = InMemoryJobQueueAdapter()
    job = JobSpec(id="job-rm", run_id="run-1", name="to-remove", command="echo 1")
    await queue.enqueue(job)
    assert await queue.size() == 1

    removed = await queue.remove("job-rm")
    assert removed is True
    assert await queue.size() == 0

    not_removed = await queue.remove("job-non-existent")
    assert not_removed is False


@pytest.mark.asyncio
async def test_local_disk_storage_lifecycle():
    """Verify temporary scratch allocation and cleanup."""
    storage = LocalDiskStorageVolumeAdapter()
    vol = await storage.allocate_scratch(job_id="job-123", size_mb=512)

    assert vol.size_mb == 512
    assert "hq-scratch-job-123" in vol.mount_path

    await storage.cleanup_scratch(vol.volume_id)


@pytest.mark.asyncio
async def test_local_subprocess_execution():
    """Verify local subprocess execution, exit code capture, and walltime."""
    log_port = InMemoryLogStreamAdapter()
    runtime = LocalSubprocessExecutionRuntimeAdapter(log_port=log_port)

    job = JobSpec(
        id="job-echo",
        run_id="run-1",
        name="echo-test",
        command="echo 'Hello Hexaqueue'",
        resources=ResourceRequirements(walltime_seconds=10),
    )

    result = await runtime.execute(job)
    assert result.exit_code == 0
    assert result.outcome == TerminalOutcome.COMPLETED

    chunks = [c async for c in log_port.stream_logs("job-echo")]
    assert len(chunks) > 0
    assert "Hello Hexaqueue" in chunks[0].content


@pytest.mark.asyncio
async def test_local_subprocess_failure():
    """Verify failed subprocess execution exit code capture."""
    log_port = InMemoryLogStreamAdapter()
    runtime = LocalSubprocessExecutionRuntimeAdapter(log_port=log_port)

    job = JobSpec(
        id="job-fail",
        run_id="run-1",
        name="fail-test",
        command="sh -c 'echo \"error output\" >&2; exit 42'",
        resources=ResourceRequirements(walltime_seconds=10),
    )

    result = await runtime.execute(job)
    assert result.exit_code == 42
    assert result.outcome == TerminalOutcome.FAILED
    assert result.error_message is not None
    assert "error output" in result.error_message


@pytest.mark.asyncio
async def test_local_subprocess_timeout():
    """Verify walltime enforcement on slow subprocesses."""
    from unittest.mock import AsyncMock, patch

    runtime = LocalSubprocessExecutionRuntimeAdapter()
    job = JobSpec(
        id="job-sleep",
        run_id="run-1",
        name="sleep-test",
        command="sleep 10",
        resources=ResourceRequirements(walltime_seconds=10),
    )

    with patch("asyncio.wait_for", side_effect=TimeoutError()):
        result = await runtime.execute(job)
        assert result.outcome == TerminalOutcome.TIMED_OUT
        assert result.exit_code == -1


@pytest.mark.asyncio
async def test_local_subprocess_terminate():
    """Verify termination of active subprocess."""
    runtime = LocalSubprocessExecutionRuntimeAdapter()
    await runtime.terminate("non-existent-job")


@pytest.mark.asyncio
async def test_mock_budget_accounting_and_rate_model():
    """Verify two-phase budget reservation, settle, and rate calculation."""
    rate_model = ZeroCostRateModelAdapter()
    estimated = rate_model.calculate_estimated_cost(ResourceRequirements())
    assert estimated == 0.0

    budget = MockBudgetAccountingAdapter(initial_balances={"tenant-1": 100.0})
    hold_id = await budget.reserve_budget(
        tenant_id="tenant-1", job_id="j1", estimated_credits=50.0
    )
    assert hold_id.startswith("hold-")

    with pytest.raises(QuotaExceededError, match="Insufficient credit balance"):
        await budget.reserve_budget(
            tenant_id="tenant-1", job_id="j2", estimated_credits=60.0
        )

    await budget.settle_budget(reservation_id=hold_id, actual_credits=30.0)


@pytest.mark.asyncio
async def test_noop_security_quarantine():
    """Verify no-op security quarantine approves collateral."""
    scanner = NoOpSecurityQuarantineAdapter()
    bundle = CollateralBundle(
        id="c1",
        job_id="j1",
        filename="data.csv",
        size_bytes=100,
        sha256_checksum="a" * 64,
        kind=CollateralKind.BUNDLE,
        tier=CollateralTier.TEMPORARY,
        state=CollateralState.UPLOADED,
        staging_uri="/tmp/staging/data.csv",
    )
    state, reason = await scanner.scan_collateral(bundle)
    assert state == CollateralState.APPROVED
    assert reason is None


@pytest.mark.asyncio
async def test_local_compute_resource_discovery():
    """Verify node capacity discovery returns valid core and memory values."""
    resource_port = LocalComputeResourceAdapter()
    capacity = await resource_port.get_node_capacity()
    assert capacity.total_cpus >= 1
    assert capacity.available_cpus >= 1
    assert capacity.total_ram_mb > 0
