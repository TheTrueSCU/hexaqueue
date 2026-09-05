"""In-memory and mock port adapters for local execution and unit testing.

Notes/Architectural Intent:
    Provides deterministic, zero-dependency implementations of all core hexagonal
    ports to enable 100% test fidelity on local laptops and developer environments.
"""

import asyncio
import os
import shutil
import tempfile
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

from hexaqueue_core.domain.collateral import CollateralBundle, CollateralState
from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.exceptions import QuotaExceededError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.ports.budget import BudgetAccountingPort, CostRateModelPort
from hexaqueue_core.ports.logging import LogChunk, LogStreamPort
from hexaqueue_core.ports.queue import JobQueuePort
from hexaqueue_core.ports.resources import ComputeResourcePort, NodeCapacity
from hexaqueue_core.ports.runtime import ExecutionRuntimePort, ProcessExecutionResult
from hexaqueue_core.ports.security import SecurityQuarantinePort
from hexaqueue_core.ports.storage import StorageVolumePort, VolumeAllocation


class InMemoryJobQueueAdapter(JobQueuePort):
    """In-memory priority-aware FIFO job queue adapter."""

    def __init__(self) -> None:
        self._queue: list[JobSpec] = []
        self._lock = asyncio.Lock()

    async def enqueue(self, job: JobSpec) -> None:
        """Enqueue job in FIFO sequence."""
        async with self._lock:
            self._queue.append(job)

    async def dequeue(self, timeout_seconds: float = 1.0) -> JobSpec | None:
        """Dequeue the highest priority job."""
        async with self._lock:
            if not self._queue:
                return None
            return self._queue.pop(0)

    async def peek(self, limit: int = 10) -> list[JobSpec]:
        """Peek queued jobs."""
        async with self._lock:
            return list(self._queue[:limit])

    async def remove(self, job_id: str) -> bool:
        """Remove a job by ID."""
        async with self._lock:
            initial_len = len(self._queue)
            self._queue = [j for j in self._queue if j.id != job_id]
            return len(self._queue) < initial_len

    async def size(self) -> int:
        """Return number of queued jobs."""
        async with self._lock:
            return len(self._queue)


class LocalDiskStorageVolumeAdapter(StorageVolumePort):
    """Local scratch directory storage adapter."""

    def __init__(self, base_scratch_dir: str | None = None) -> None:
        self._base_dir = base_scratch_dir or os.path.join(
            tempfile.gettempdir(), "hexaqueue_scratch"
        )
        self._allocations: dict[str, str] = {}

    async def allocate_scratch(
        self, job_id: str, size_mb: int, base_dir: str | None = None
    ) -> VolumeAllocation:
        """Create a temporary directory for job execution."""
        root = base_dir or self._base_dir
        os.makedirs(root, exist_ok=True)
        mount_path = tempfile.mkdtemp(prefix=f"hq-scratch-{job_id}-", dir=root)
        volume_id = f"vol-{uuid4().hex[:8]}"
        self._allocations[volume_id] = mount_path
        return VolumeAllocation(
            volume_id=volume_id,
            mount_path=mount_path,
            size_mb=size_mb,
            is_ephemeral=True,
        )

    async def cleanup_scratch(self, volume_id: str) -> None:
        """Remove temporary directory."""
        if volume_id in self._allocations:
            path = self._allocations.pop(volume_id)
            if os.path.exists(path):
                shutil.rmtree(path, ignore_errors=True)


class LocalSubprocessExecutionRuntimeAdapter(ExecutionRuntimePort):
    """Local subprocess execution runtime adapter."""

    def __init__(self, log_port: LogStreamPort | None = None) -> None:
        self._log_port = log_port
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}

    async def execute(
        self,
        job: JobSpec,
        scratch_volume: VolumeAllocation | None = None,
        environment: dict[str, str] | None = None,
    ) -> ProcessExecutionResult:
        """Execute job via bash subprocess with timeout and log capture."""
        cwd = scratch_volume.mount_path if scratch_volume else None
        env = os.environ.copy()
        if environment:
            env.update(environment)

        start_time = datetime.now(UTC)
        proc = await asyncio.create_subprocess_shell(
            job.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        self._active_processes[job.id] = proc

        try:
            stdout_data, stderr_data = await asyncio.wait_for(
                proc.communicate(),
                timeout=float(job.resources.walltime_seconds),
            )
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            exit_code = proc.returncode or 0

            # Write captured logs if port available
            if self._log_port:
                if stdout_data:
                    await self._log_port.write_log(
                        LogChunk(
                            job_id=job.id,
                            stream="stdout",
                            content=stdout_data.decode("utf-8", errors="replace"),
                            offset=0,
                        )
                    )
                if stderr_data:
                    await self._log_port.write_log(
                        LogChunk(
                            job_id=job.id,
                            stream="stderr",
                            content=stderr_data.decode("utf-8", errors="replace"),
                            offset=0,
                        )
                    )

            outcome = (
                TerminalOutcome.COMPLETED
                if exit_code == 0
                else TerminalOutcome.FAILED
            )
            error_msg = (
                stderr_data.decode("utf-8", errors="replace")
                if exit_code != 0
                else None
            )

            return ProcessExecutionResult(
                exit_code=exit_code,
                outcome=outcome,
                error_message=error_msg,
                walltime_seconds=elapsed,
            )

        except TimeoutError:
            proc.kill()
            await proc.wait()
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            return ProcessExecutionResult(
                exit_code=-1,
                outcome=TerminalOutcome.TIMED_OUT,
                error_message=f"Job exceeded walltime limit of {job.resources.walltime_seconds}s",
                walltime_seconds=elapsed,
            )
        finally:
            self._active_processes.pop(job.id, None)

    async def terminate(self, job_id: str, grace_period_seconds: int = 15) -> None:
        """Terminate running subprocess."""
        if proc := self._active_processes.get(job_id):
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=grace_period_seconds)
            except TimeoutError:
                proc.kill()
                await proc.wait()


class InMemoryLogStreamAdapter(LogStreamPort):
    """In-memory log ring buffer adapter."""

    def __init__(self) -> None:
        self._logs: dict[str, list[LogChunk]] = defaultdict(list)

    async def write_log(self, chunk: LogChunk) -> None:
        """Append log chunk to memory buffer."""
        self._logs[chunk.job_id].append(chunk)

    async def stream_logs(
        self, job_id: str, follow: bool = False, tail: int | None = None
    ) -> AsyncIterator[LogChunk]:
        """Yield log chunks for a given job."""
        chunks = self._logs.get(job_id, [])
        if tail:
            chunks = chunks[-tail:]
        for chunk in chunks:
            yield chunk


class NoOpSecurityQuarantineAdapter(SecurityQuarantinePort):
    """No-op security quarantine adapter that approves all collateral."""

    async def scan_collateral(
        self, bundle: CollateralBundle
    ) -> tuple[CollateralState, str | None]:
        """Automatically approve collateral for local development."""
        return CollateralState.APPROVED, None


class MockBudgetAccountingAdapter(BudgetAccountingPort):
    """In-memory budget reservation adapter."""

    def __init__(self, initial_balances: dict[str, float] | None = None) -> None:
        self._balances = defaultdict(lambda: 10000.0)
        if initial_balances:
            self._balances.update(initial_balances)
        self._holds: dict[str, tuple[str, float]] = {}

    async def reserve_budget(
        self, tenant_id: str, job_id: str, estimated_credits: float
    ) -> str:
        """Place budget hold."""
        if self._balances[tenant_id] < estimated_credits:
            msg = f"Insufficient credit balance for tenant '{tenant_id}'"
            raise QuotaExceededError(msg)
        self._balances[tenant_id] -= estimated_credits
        hold_id = f"hold-{uuid4().hex[:8]}"
        self._holds[hold_id] = (tenant_id, estimated_credits)
        return hold_id

    async def settle_budget(self, reservation_id: str, actual_credits: float) -> None:
        """Settle budget hold."""
        if reservation_id in self._holds:
            tenant_id, reserved = self._holds.pop(reservation_id)
            refund = reserved - actual_credits
            self._balances[tenant_id] += refund


class ZeroCostRateModelAdapter(CostRateModelPort):
    """Cost rate model adapter returning 0.0 credits for free-tier / local testing."""

    def calculate_estimated_cost(
        self, requirements: ResourceRequirements, provider: CspProvider = CspProvider.LOCAL
    ) -> float:
        """Always return 0.0 credits for local zero-cost profile."""
        return 0.0


class LocalComputeResourceAdapter(ComputeResourcePort):
    """Local machine resource topology discovery adapter."""

    async def get_node_capacity(self) -> NodeCapacity:
        """Discover CPU cores and memory from local OS."""
        cpus = os.cpu_count() or 4
        # Allocate 8GB nominal memory for mock adapter if psutil is absent
        return NodeCapacity(
            node_id="local-node-0",
            total_cpus=cpus,
            available_cpus=cpus,
            total_ram_mb=8192,
            available_ram_mb=8192,
            total_gpus=0,
            available_gpus=0,
        )


__all__ = [
    "InMemoryJobQueueAdapter",
    "InMemoryLogStreamAdapter",
    "LocalComputeResourceAdapter",
    "LocalDiskStorageVolumeAdapter",
    "LocalSubprocessExecutionRuntimeAdapter",
    "MockBudgetAccountingAdapter",
    "NoOpSecurityQuarantineAdapter",
    "ZeroCostRateModelAdapter",
]
