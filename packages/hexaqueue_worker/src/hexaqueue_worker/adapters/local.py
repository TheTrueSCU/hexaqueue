"""Local subprocess compute node worker daemon adapter.

Notes/Architectural Intent:
    Polls ready jobs from JobQueuePort, allocates isolated scratch storage via StorageVolumePort,
    runs commands via ExecutionRuntimePort, and updates terminal outcomes via SchedulerControllerPort.
    Ensures zero cross-job pollution by cleaning up ephemeral scratch allocations in a finally block.
"""

import asyncio
import contextlib
import importlib
from typing import Any

from hexaqueue_core.adapters.runtime.local import LocalSubprocessExecutionRuntimeAdapter
from hexaqueue_core.adapters.storage.local import LocalDiskStorageVolumeAdapter
from hexaqueue_core.domain.gpu import GpuAllocation
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.ports.gpu import GpuDeviceManagerPort
from hexaqueue_core.ports.logging import LogStreamPort
from hexaqueue_core.ports.queue import JobQueuePort
from hexaqueue_core.ports.runtime import ExecutionRuntimePort, ProcessExecutionResult
from hexaqueue_core.ports.storage import StorageVolumePort, VolumeAllocation
from hexaqueue_worker.domain.models import WorkerConfig, WorkerMetrics
from hexaqueue_worker.ports.worker import WorkerDaemonPort


def _capture_sentry_worker_exception(
    exc: Exception,
    worker_id: str,
    job_id: str,
    queue: str,
    command: str,
) -> None:
    """Push worker crash failure context to Sentry scope if sentry_sdk is active.

    Args:
        exc: Unhandled exception raised during job execution.
        worker_id: Unique identifier of the worker daemon.
        job_id: Unique identifier of the job that crashed.
        queue: Name or identifier of the queue.
        command: Command string executed by the job.

    Notes/Architectural Intent:
        Integrates optional Sentry error monitoring without adding a hard dependency
        on sentry-sdk. Dynamically loads sentry_sdk at runtime and safely tags execution metadata.
    """
    with contextlib.suppress(Exception):
        sentry_sdk = importlib.import_module("sentry_sdk")
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("worker_id", worker_id)
            scope.set_tag("job_id", job_id)
            scope.set_tag("queue", queue)
            scope.set_tag("command", command)
            sentry_sdk.capture_exception(exc)


class LocalSubprocessWorker(WorkerDaemonPort):
    """Local subprocess execution worker daemon.

    Args:
        queue: JobQueuePort to dequeue ready jobs from.
        controller: Optional SchedulerControllerPort to update job terminal outcomes.
        runtime: Optional ExecutionRuntimePort (defaults to LocalSubprocessExecutionRuntimeAdapter).
        storage: Optional StorageVolumePort (defaults to LocalStorageVolumeAdapter).
        log_port: Optional LogStreamPort for streaming stdout/stderr.
        gpu_manager: Optional GpuDeviceManagerPort for dynamic GPU allocation and CUDA masking.
        config: Optional WorkerConfig for concurrency and polling parameters.
    """

    def __init__(
        self,
        queue: JobQueuePort,
        controller: Any | None = None,
        runtime: ExecutionRuntimePort | None = None,
        storage: StorageVolumePort | None = None,
        log_port: LogStreamPort | None = None,
        gpu_manager: GpuDeviceManagerPort | None = None,
        config: WorkerConfig | None = None,
    ) -> None:
        self._queue = queue
        self._controller = controller
        self._log_port = log_port
        self._gpu_manager = gpu_manager
        self._runtime = runtime or LocalSubprocessExecutionRuntimeAdapter(
            log_port=self._log_port
        )
        self._storage = storage or LocalDiskStorageVolumeAdapter()
        self._config = config or WorkerConfig()

        self._semaphore = asyncio.Semaphore(self._config.concurrency)
        self._active_jobs: set[str] = set()
        self._running = False
        self._worker_tasks: set[asyncio.Task[None]] = set()
        self._loop_task: asyncio.Task[None] | None = None

        self._total_executed = 0
        self._total_completed = 0
        self._total_failed = 0
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start worker polling loop in background task."""
        async with self._lock:
            if self._running:
                return
            self._running = True
            self._loop_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Gracefully stop worker loop and await in-flight tasks."""
        async with self._lock:
            if not self._running:
                return
            self._running = False

        if self._loop_task:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
            self._loop_task = None

        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
            self._worker_tasks.clear()

    async def _poll_loop(self) -> None:
        """Main queue polling loop."""
        while self._running:
            try:
                # Wait for concurrency slot
                await self._semaphore.acquire()
                try:
                    job = await self._queue.dequeue(
                        timeout_seconds=self._config.poll_interval_seconds
                    )
                except (Exception, asyncio.CancelledError):
                    self._semaphore.release()
                    raise

                if job is None:
                    self._semaphore.release()
                    await asyncio.sleep(self._config.poll_interval_seconds)
                    continue

                task = asyncio.create_task(self._process_job_slot(job))
                self._worker_tasks.add(task)
                task.add_done_callback(self._worker_tasks.discard)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(self._config.poll_interval_seconds)

    async def _process_job_slot(self, job: JobSpec) -> None:
        """Process job with acquired semaphore slot."""
        try:
            await self.execute_job(job)
        finally:
            self._semaphore.release()

    async def execute_job(self, job: JobSpec) -> ProcessExecutionResult:
        """Execute a single job within isolated scratch storage and report status."""
        async with self._lock:
            self._active_jobs.add(job.id)
            self._total_executed += 1

        gpu_alloc: GpuAllocation | None = None
        scratch_vol: VolumeAllocation | None = None
        try:
            # 1. Allocate dedicated GPU accelerators if requested
            env = dict(job.env)
            if self._gpu_manager and job.resources.gpus > 0:
                gpu_alloc = await self._gpu_manager.allocate_gpus(
                    job_id=job.id,
                    count=job.resources.gpus,
                    model=job.resources.gpu_model,
                    min_vram_mb=job.resources.vram_mb,
                )
                env["CUDA_VISIBLE_DEVICES"] = gpu_alloc.cuda_visible_devices_env

            # 2. Allocate isolated scratch workspace
            scratch_vol = await self._storage.allocate_scratch(
                job_id=job.id,
                size_mb=job.resources.scratch_mb,
                base_dir=self._config.scratch_base_dir,
            )

            # 3. Execute process via runtime
            result = await self._runtime.execute(
                job=job,
                scratch_volume=scratch_vol,
                environment=env,
            )

            # 4. Notify controller if configured
            if self._controller:
                await self._controller.update_job_outcome(
                    job_id=job.id,
                    outcome=result.outcome,
                    reason=result.error_message,
                )

            async with self._lock:
                if result.exit_code == 0:
                    self._total_completed += 1
                else:
                    self._total_failed += 1

            return result
        except Exception as exc:
            queue_name = str(
                getattr(
                    self._queue,
                    "name",
                    getattr(
                        self._queue,
                        "queue_name",
                        getattr(job, "queue", "default"),
                    ),
                )
            )
            _capture_sentry_worker_exception(
                exc=exc,
                worker_id=self._config.worker_id,
                job_id=job.id,
                queue=queue_name,
                command=job.command,
            )
            if self._controller:
                with contextlib.suppress(Exception):
                    await self._controller.update_job_outcome(
                        job_id=job.id,
                        outcome=TerminalOutcome.FAILED,
                        reason=f"Worker failure: {exc}",
                    )
            async with self._lock:
                self._total_failed += 1
            raise
        finally:
            # 5. Clean up scratch storage (isolated so failures cannot strand GPU/active-job tracking)
            try:
                if scratch_vol and scratch_vol.is_ephemeral:
                    await self._storage.cleanup_scratch(scratch_vol.volume_id)
            finally:
                # 6. Release reserved GPU accelerators
                try:
                    if gpu_alloc and self._gpu_manager:
                        await self._gpu_manager.release_gpus(job.id)
                finally:
                    async with self._lock:
                        self._active_jobs.discard(job.id)

    async def get_metrics(self) -> WorkerMetrics:
        """Retrieve real-time operational worker metrics."""
        async with self._lock:
            return WorkerMetrics(
                worker_id=self._config.worker_id,
                active_jobs=len(self._active_jobs),
                total_executed=self._total_executed,
                total_completed=self._total_completed,
                total_failed=self._total_failed,
                is_running=self._running,
            )


__all__ = [
    "LocalSubprocessWorker",
]
