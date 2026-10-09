"""Local subprocess compute node worker daemon adapter.

Notes/Architectural Intent:
    Polls ready jobs from JobQueuePort, allocates isolated scratch storage via StorageVolumePort,
    runs commands via ExecutionRuntimePort, and updates terminal outcomes via SchedulerControllerPort.
    Ensures zero cross-job pollution by cleaning up ephemeral scratch allocations in a finally block.
"""

import asyncio
import contextlib
import gzip
import hashlib
import importlib
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from hexaqueue_collateral.ports.service import CollateralServicePort
from hexaqueue_core.adapters.runtime.local import LocalSubprocessExecutionRuntimeAdapter
from hexaqueue_core.adapters.storage.local import LocalDiskStorageVolumeAdapter
from hexaqueue_core.adapters.storage.presigned import InMemoryPresignedStorageAdapter
from hexaqueue_core.domain.collateral import CollateralBundle, CollateralState
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.gpu import GpuAllocation
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.retention import LogRetentionPolicy
from hexaqueue_core.ports.gpu import GpuDeviceManagerPort
from hexaqueue_core.ports.logging import LogStreamPort
from hexaqueue_core.ports.queue import JobQueuePort
from hexaqueue_core.ports.runtime import ExecutionRuntimePort, ProcessExecutionResult
from hexaqueue_core.ports.storage import (
    PresignedStoragePort,
    StorageVolumePort,
    VolumeAllocation,
)
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
        presigned_storage: Optional PresignedStoragePort for presigned storage operations.
        collateral_service: Optional CollateralServicePort for CAS collateral caching and retrieval.
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
        presigned_storage: PresignedStoragePort | None = None,
        collateral_service: CollateralServicePort | None = None,
    ) -> None:
        self._queue = queue
        self._controller = controller
        self._log_port = log_port
        self._gpu_manager = gpu_manager
        self._presigned_storage = presigned_storage
        self._collateral_service = collateral_service
        self._runtime = runtime or LocalSubprocessExecutionRuntimeAdapter(
            log_port=self._log_port
        )
        self._storage = storage or LocalDiskStorageVolumeAdapter()
        self._config = config or WorkerConfig()

        self._collateral_cache_dir = (
            Path(self._config.collateral_cache_dir)
            if self._config.collateral_cache_dir
            else Path(tempfile.gettempdir())
            / f"hexaqueue_worker_cas_{self._config.worker_id}"
        )
        self._collateral_cache_dir.mkdir(parents=True, exist_ok=True)
        self._cached_collateral_hashes: set[str] = set()
        for p in self._collateral_cache_dir.iterdir():
            if p.is_dir() and len(p.name) == 64:
                self._cached_collateral_hashes.add(p.name)

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

            # 2.5 Rehydrate required collateral bundles into scratch workspace
            if job.collateral_ids:
                await self._rehydrate_collateral(job, scratch_vol)

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

    @property
    def cached_collateral_hashes(self) -> frozenset[str]:
        """Return the set of CAS SHA-256 hashes currently held in local worker cache.

        Returns:
            Frozenset of hex-encoded SHA-256 digests.
        """
        return frozenset(self._cached_collateral_hashes)

    async def heartbeat_controller(self) -> Any:
        """Dispatch a heartbeat pulse to the controller reporting active jobs and cached hashes.

        Returns:
            Controller heartbeat response or None if controller is not wired.
        """
        if self._controller and hasattr(self._controller, "heartbeat_node"):
            return await self._controller.heartbeat_node(
                worker_id=self._config.worker_id,
                active_job_ids=list(self._active_jobs),
                cached_collateral_hashes=list(self._cached_collateral_hashes),
            )
        return None

    async def _fetch_collateral_payload(
        self,
        bundle: CollateralBundle,
        cid: str,
        expected_sha256: str,
        safe_filename: str,
    ) -> bytes:
        """Fetch raw collateral payload bytes across local disk, storage adapter, or HTTP.

        Args:
            bundle: CollateralBundle domain instance.
            cid: Collateral identifier string.
            expected_sha256: Expected SHA-256 digest.
            safe_filename: Sanitized target filename.

        Returns:
            Raw bytes payload of the collateral file.

        Raises:
            HexaqueueError: If payload cannot be downloaded or resolved.
        """
        if bundle.active_uri and Path(bundle.active_uri).exists():
            return Path(bundle.active_uri).read_bytes()

        if self._collateral_service is None:
            msg = f"Cannot fetch collateral '{cid}': collateral service not configured"
            raise HexaqueueError(msg)

        download_url = await self._collateral_service.get_download_url(cid)
        if download_url.startswith("file://"):
            local_path = Path(download_url.removeprefix("file://"))
            if local_path.exists():
                return local_path.read_bytes()

        if self._presigned_storage and isinstance(
            self._presigned_storage, InMemoryPresignedStorageAdapter
        ):
            key = f"collateral/{expected_sha256}/{safe_filename}"
            return self._presigned_storage.get_object(key)

        if download_url.startswith(("http://", "https://")):
            req = urllib.request.Request(download_url)  # noqa: S310
            with urllib.request.urlopen(req) as resp:  # noqa: S310
                return resp.read()

        msg = f"Failed to retrieve payload for collateral bundle '{cid}' from '{download_url}'"
        raise HexaqueueError(msg)

    async def _ensure_cached_collateral(self, cid: str) -> tuple[Path, str]:
        """Ensure a single collateral bundle is cached in local CAS and verified.

        Args:
            cid: Collateral identifier string.

        Returns:
            Tuple of (cached_file_path, safe_filename).

        Raises:
            HexaqueueError: If bundle is missing, unapproved, fails verification, or cannot be cached.
        """
        if self._collateral_service is None:
            msg = (
                f"Cannot rehydrate collateral '{cid}': no collateral service configured"
            )
            raise HexaqueueError(msg)

        bundle = await self._collateral_service.get_bundle(cid)
        if bundle.state != CollateralState.APPROVED:
            msg = (
                f"Collateral bundle '{cid}' is in state '{bundle.state}', "
                f"not APPROVED. Refusing to inject into job workspace."
            )
            raise HexaqueueError(msg)

        expected_sha256 = bundle.sha256_checksum.lower().strip()
        raw_filename = Path(bundle.filename).name
        safe_filename = (
            raw_filename if raw_filename not in ("", ".", "..") else f"collateral_{cid}"
        )

        cas_dir = self._collateral_cache_dir / expected_sha256
        cached_file = cas_dir / safe_filename

        if not cached_file.exists():
            cas_dir.mkdir(parents=True, exist_ok=True)
            data = await self._fetch_collateral_payload(
                bundle=bundle,
                cid=cid,
                expected_sha256=expected_sha256,
                safe_filename=safe_filename,
            )
            actual_sha256 = hashlib.sha256(data).hexdigest()
            if actual_sha256 != expected_sha256:
                msg = (
                    f"Collateral integrity verification failed for '{cid}': "
                    f"expected SHA-256 {expected_sha256}, got {actual_sha256}"
                )
                raise HexaqueueError(msg)
            cached_file.write_bytes(data)

        self._cached_collateral_hashes.add(expected_sha256)
        return cached_file, safe_filename

    async def _rehydrate_collateral(
        self,
        job: JobSpec,
        scratch_volume: VolumeAllocation,
    ) -> None:
        """Fetch, verify, cache, and symlink required collateral bundles into scratch volume.

        Args:
            job: Job specification requesting collateral.
            scratch_volume: Ephemeral volume allocation representing execution cwd.

        Raises:
            HexaqueueError: If collateral is missing, unapproved, fails checksum, or cannot be resolved.

        Notes/Architectural Intent:
            Content-addressable storage rehydration downloads bundles once into a shared
            node CAS directory named by SHA-256 digest, then creates zero-copy symlinks
            into each job's isolated scratch directory.
        """
        if not job.collateral_ids:
            return

        mount_path = Path(scratch_volume.mount_path)
        for cid in job.collateral_ids:
            cached_file, safe_filename = await self._ensure_cached_collateral(cid)
            dest_target = mount_path / safe_filename
            if dest_target.exists() or dest_target.is_symlink():
                dest_target.unlink()
            try:
                dest_target.symlink_to(cached_file)
            except OSError:
                shutil.copy2(cached_file, dest_target)

    async def get_metrics(self) -> WorkerMetrics:
        """Retrieve real-time operational worker metrics."""
        async with self._lock:
            return WorkerMetrics(
                worker_id=self._config.worker_id,
                active_jobs=len(self._active_jobs),
                total_executed=self._total_executed,
                total_completed=self._total_completed,
                total_failed=self._total_failed,
                cached_collateral_count=len(self._cached_collateral_hashes),
                is_running=self._running,
            )

    async def upload_job_logs(
        self,
        job_id: str,
        outcome: TerminalOutcome,
        log_data: str | bytes,
        compress: bool = True,
    ) -> str:
        """Upload finished execution logs directly to presigned storage bucket.

        Args:
            job_id: Finished job identifier.
            outcome: TerminalOutcome for differential retention resolution.
            log_data: Log text content or raw bytes.
            compress: Whether to gzip compress the log payload.

        Returns:
            Destination storage key, or empty string if presigned storage is not configured.

        Notes/Architectural Intent:
            During CLEANUP phase, workers bypass the server REST API by directly
            archiving logs into object storage with differential retention tags
            (ShortPass for COMPLETED vs LongFail for failures).
        """
        if self._presigned_storage is None:
            return ""

        policy = LogRetentionPolicy.for_outcome(outcome)
        ext = ".log.gz" if compress else ".log"
        key = f"logs/{job_id}/stdout_stderr{ext}"
        payload = log_data.encode("utf-8") if isinstance(log_data, str) else log_data
        if compress:
            payload = gzip.compress(payload)

        await self._presigned_storage.generate_presigned_upload_url(
            key=key,
            content_type="application/gzip" if compress else "text/plain",
            expires_in_seconds=300,
        )
        if isinstance(self._presigned_storage, InMemoryPresignedStorageAdapter):
            self._presigned_storage.put_object(
                key=key,
                data=payload,
                metadata={policy.tag_key: policy.tag_value},
            )
        return key


__all__ = [
    "LocalSubprocessWorker",
]
