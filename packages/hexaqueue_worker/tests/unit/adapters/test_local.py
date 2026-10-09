"""Unit tests for LocalSubprocessWorker adapter."""

import asyncio
import importlib
from unittest.mock import AsyncMock

import pytest

from hexaqueue_core.adapters.logging.in_memory import InMemoryLogStreamAdapter
from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.adapters.storage.in_memory import InMemoryStorageVolumeAdapter
from hexaqueue_core.adapters.storage.presigned import InMemoryPresignedStorageAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_worker.adapters.local import LocalSubprocessWorker
from hexaqueue_worker.domain.models import WorkerConfig


@pytest.mark.asyncio
async def test_worker_execute_job_success() -> None:
    """Verify single job execution, scratch lifecycle, and exit code 0."""
    queue = InMemoryJobQueueAdapter()
    storage = InMemoryStorageVolumeAdapter()
    log_port = InMemoryLogStreamAdapter()
    controller = AsyncMock()

    worker = LocalSubprocessWorker(
        queue=queue,
        controller=controller,
        storage=storage,
        log_port=log_port,
        config=WorkerConfig(worker_id="test-worker-1"),
    )

    job = JobSpec(
        id="job-1",
        run_id="run-1",
        name="echo-test",
        command="echo 'Hexaqueue Worker Running'",
        resources=ResourceRequirements(walltime_seconds=10, scratch_mb=50),
    )

    result = await worker.execute_job(job)
    assert result.exit_code == 0
    assert result.outcome == TerminalOutcome.COMPLETED

    # Verify controller notification
    controller.update_job_outcome.assert_awaited_once_with(
        job_id=job.id,
        outcome=TerminalOutcome.COMPLETED,
        reason=None,
    )

    # Verify scratch was allocated and cleaned up
    assert len(storage._allocations) == 0

    # Verify metrics
    metrics = await worker.get_metrics()
    assert metrics.worker_id == "test-worker-1"
    assert metrics.total_executed == 1
    assert metrics.total_completed == 1
    assert metrics.total_failed == 0
    assert metrics.active_jobs == 0


@pytest.mark.asyncio
async def test_worker_execute_job_failure() -> None:
    """Verify failed job exit code capture and status propagation."""
    queue = InMemoryJobQueueAdapter()
    storage = InMemoryStorageVolumeAdapter()
    controller = AsyncMock()

    worker = LocalSubprocessWorker(
        queue=queue,
        controller=controller,
        storage=storage,
    )

    job = JobSpec(
        id="job-fail",
        run_id="run-1",
        name="fail-test",
        command="sh -c 'echo \"failed task\" >&2; exit 7'",
        resources=ResourceRequirements(walltime_seconds=10),
    )

    result = await worker.execute_job(job)
    assert result.exit_code == 7
    assert result.outcome == TerminalOutcome.FAILED
    assert result.error_message is not None
    assert "failed task" in result.error_message

    controller.update_job_outcome.assert_awaited_once_with(
        job_id=job.id,
        outcome=TerminalOutcome.FAILED,
        reason=result.error_message,
    )

    metrics = await worker.get_metrics()
    assert metrics.total_executed == 1
    assert metrics.total_failed == 1
    assert metrics.total_completed == 0


@pytest.mark.asyncio
async def test_worker_poll_loop_e2e() -> None:
    """Verify background worker loop dequeuing, executing, and graceful shutdown."""
    queue = InMemoryJobQueueAdapter()
    storage = InMemoryStorageVolumeAdapter()
    controller = AsyncMock()

    worker = LocalSubprocessWorker(
        queue=queue,
        controller=controller,
        storage=storage,
        config=WorkerConfig(concurrency=2, poll_interval_seconds=0.01),
    )

    j1 = JobSpec(
        id="j1",
        run_id="run-1",
        name="j1",
        command="echo 1",
        resources=ResourceRequirements(walltime_seconds=10),
    )
    j2 = JobSpec(
        id="j2",
        run_id="run-1",
        name="j2",
        command="echo 2",
        resources=ResourceRequirements(walltime_seconds=10),
    )

    await queue.enqueue(j1)
    await queue.enqueue(j2)

    await worker.start()
    # Idempotent start
    await worker.start()

    # Allow poll loop to process both jobs
    for _ in range(50):
        metrics = await worker.get_metrics()
        if metrics.total_executed >= 2:
            break
        await asyncio.sleep(0.05)

    await worker.stop()
    # Idempotent stop
    await worker.stop()

    metrics = await worker.get_metrics()
    assert metrics.total_executed == 2
    assert metrics.total_completed == 2
    assert metrics.is_running is False


@pytest.mark.asyncio
async def test_worker_execute_job_with_gpu_allocation() -> None:
    """Verify GPU allocation, CUDA_VISIBLE_DEVICES injection, and post-job GPU release."""
    queue = InMemoryJobQueueAdapter()
    storage = InMemoryStorageVolumeAdapter()
    controller = AsyncMock()

    from hexaqueue_core.domain.gpu import GpuDevice
    from hexaqueue_worker.adapters.gpu import MockGpuDeviceManagerAdapter

    gpu_mgr = MockGpuDeviceManagerAdapter(
        devices=[
            GpuDevice(
                index=0,
                name="NVIDIA A100",
                uuid="GPU-0",
                total_vram_mb=81920,
                free_vram_mb=81920,
            ),
        ]
    )

    worker = LocalSubprocessWorker(
        queue=queue,
        controller=controller,
        storage=storage,
        gpu_manager=gpu_mgr,
    )

    import sys

    job = JobSpec(
        id="gpu-job-1",
        run_id="run-1",
        name="gpu-test",
        command=f"{sys.executable} -c \"import os; assert os.environ.get('CUDA_VISIBLE_DEVICES') == '0'\"",
        resources=ResourceRequirements(gpus=1, walltime_seconds=10),
    )

    result = await worker.execute_job(job)
    exit_code = result.exit_code
    outcome = result.outcome
    assert exit_code == 0
    assert outcome == TerminalOutcome.COMPLETED

    # Verify GPU was released
    active_allocs = await gpu_mgr.get_active_allocations()
    count = len(active_allocs)
    assert count == 0


@pytest.mark.asyncio
async def test_worker_execute_job_gpu_released_on_failure() -> None:
    """Verify GPU is cleanly released even when job execution fails."""
    queue = InMemoryJobQueueAdapter()
    storage = InMemoryStorageVolumeAdapter()
    controller = AsyncMock()

    from hexaqueue_core.domain.gpu import GpuDevice
    from hexaqueue_worker.adapters.gpu import MockGpuDeviceManagerAdapter

    gpu_mgr = MockGpuDeviceManagerAdapter(
        devices=[
            GpuDevice(
                index=0,
                name="NVIDIA A100",
                uuid="GPU-0",
                total_vram_mb=81920,
                free_vram_mb=81920,
            ),
        ]
    )

    worker = LocalSubprocessWorker(
        queue=queue,
        controller=controller,
        storage=storage,
        gpu_manager=gpu_mgr,
    )

    import sys

    job = JobSpec(
        id="gpu-job-fail",
        run_id="run-1",
        name="gpu-fail-test",
        command=f'{sys.executable} -c "import sys; sys.exit(3)"',
        resources=ResourceRequirements(gpus=1, walltime_seconds=10),
    )

    result = await worker.execute_job(job)
    exit_code = result.exit_code
    outcome = result.outcome
    assert exit_code == 3
    assert outcome == TerminalOutcome.FAILED

    # Verify GPU was still released
    active_allocs = await gpu_mgr.get_active_allocations()
    count = len(active_allocs)
    assert count == 0


@pytest.mark.asyncio
async def test_worker_init_and_resource_branching() -> None:
    """Verify storage instance preservation and zero-gpu/non-ephemeral scratch branches."""
    from hexaqueue_core.ports.storage import VolumeAllocation

    queue = InMemoryJobQueueAdapter()
    storage = InMemoryStorageVolumeAdapter()
    gpu_mgr = AsyncMock()

    worker = LocalSubprocessWorker(
        queue=queue,
        storage=storage,
        gpu_manager=gpu_mgr,
    )
    # Storage instance preserved (or to and)
    assert worker._storage is storage

    # 1. Job with gpus=0 -> gpu_manager is NOT invoked
    job_no_gpu = JobSpec(
        id="j-no-gpu",
        run_id="r1",
        name="no-gpu",
        command="true",
        resources=ResourceRequirements(gpus=0),
    )
    await worker.execute_job(job_no_gpu)
    assert gpu_mgr.allocate_gpus.called is False
    assert gpu_mgr.release_gpus.called is False

    # 2. Non-ephemeral scratch volume -> cleanup_scratch is NOT called
    mock_storage = AsyncMock()
    mock_vol = VolumeAllocation(
        volume_id="vol-persist",
        mount_path="/tmp",
        size_mb=10,
        is_ephemeral=False,
    )
    mock_storage.allocate_scratch.return_value = mock_vol

    worker_persist = LocalSubprocessWorker(
        queue=queue,
        storage=mock_storage,
    )
    await worker_persist.execute_job(job_no_gpu)
    assert mock_storage.cleanup_scratch.called is False


@pytest.mark.asyncio
async def test_worker_execute_job_crash_sentry_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify Sentry scope tagging and exception capture during worker crash."""
    from unittest.mock import MagicMock

    queue = InMemoryJobQueueAdapter()
    storage = InMemoryStorageVolumeAdapter()
    mock_runtime = AsyncMock()
    mock_runtime.execute.side_effect = RuntimeError("Fatal node crash")

    mock_sentry = MagicMock()
    mock_scope = MagicMock()
    mock_sentry.push_scope.return_value.__enter__.return_value = mock_scope

    orig_import_module = importlib.import_module

    def fake_import_module(name: str, *args, **kwargs):
        if name == "sentry_sdk":
            return mock_sentry
        return orig_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    worker = LocalSubprocessWorker(
        queue=queue,
        storage=storage,
        runtime=mock_runtime,
        config=WorkerConfig(worker_id="crash-worker-42"),
    )

    job = JobSpec(
        id="job-crash-101",
        run_id="run-99",
        name="crash-job",
        command="exit_with_sigkill",
    )

    with pytest.raises(RuntimeError, match="Fatal node crash"):
        await worker.execute_job(job)

    assert mock_sentry.push_scope.called is True
    mock_scope.set_tag.assert_any_call("worker_id", "crash-worker-42")
    mock_scope.set_tag.assert_any_call("job_id", "job-crash-101")
    mock_scope.set_tag.assert_any_call("queue", "default")
    mock_scope.set_tag.assert_any_call("command", "exit_with_sigkill")
    assert mock_sentry.capture_exception.called is True

    metrics = await worker.get_metrics()
    assert metrics.total_failed == 1


@pytest.mark.asyncio
async def test_worker_execute_job_crash_without_sentry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify worker crash gracefully proceeds when sentry_sdk is not installed."""
    queue = InMemoryJobQueueAdapter()
    storage = InMemoryStorageVolumeAdapter()
    mock_runtime = AsyncMock()
    crash_error = RuntimeError("Fatal node crash without sentry")
    mock_runtime.execute.side_effect = crash_error

    orig_import_module = importlib.import_module

    def fake_import_module(name: str, *args, **kwargs):
        if name == "sentry_sdk":
            msg = "No module named sentry_sdk"
            raise ModuleNotFoundError(msg)
        return orig_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    worker = LocalSubprocessWorker(
        queue=queue,
        storage=storage,
        runtime=mock_runtime,
        config=WorkerConfig(worker_id="crash-worker-43"),
    )

    job = JobSpec(
        id="job-crash-102",
        run_id="run-99",
        name="crash-job",
        command="exit_with_sigkill",
    )

    with pytest.raises(RuntimeError, match="Fatal node crash without sentry"):
        await worker.execute_job(job)

    metrics = await worker.get_metrics()
    assert metrics.total_failed == 1


@pytest.mark.asyncio
async def test_worker_upload_job_logs() -> None:
    """Verify worker differential log uploading to presigned storage."""
    queue = InMemoryJobQueueAdapter()
    worker_no_storage = LocalSubprocessWorker(queue=queue)
    empty_key = await worker_no_storage.upload_job_logs(
        job_id="job-log-1",
        outcome=TerminalOutcome.COMPLETED,
        log_data="Execution successful\n",
    )
    assert empty_key == ""

    presigned_storage = InMemoryPresignedStorageAdapter(
        endpoint_url="https://s3.example.com"
    )
    worker = LocalSubprocessWorker(queue=queue, presigned_storage=presigned_storage)

    # Test completed job (ShortPass)
    key_completed = await worker.upload_job_logs(
        job_id="job-log-pass",
        outcome=TerminalOutcome.COMPLETED,
        log_data="Step 1 OK\nStep 2 OK\n",
        compress=True,
    )
    assert key_completed == "logs/job-log-pass/stdout_stderr.log.gz"

    # Test failed job (LongFail)
    key_failed = await worker.upload_job_logs(
        job_id="job-log-fail",
        outcome=TerminalOutcome.FAILED,
        log_data="Traceback: Fatal error\n",
        compress=False,
    )
    assert key_failed == "logs/job-log-fail/stdout_stderr.log"
