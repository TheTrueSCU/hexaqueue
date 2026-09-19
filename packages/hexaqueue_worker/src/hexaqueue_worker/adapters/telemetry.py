"""Local system telemetry collector adapter.

Notes/Architectural Intent:
    Collects real-time hardware telemetry (CPU load, memory consumption, scratch storage, GPU)
    from the host environment using standard POSIX interfaces (/proc/meminfo, statvfs, getloadavg)
    and distributes pulses to local and remote subscribers without blocking worker threads.
"""

import asyncio
import contextlib
import os
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from hexaqueue_worker.domain.telemetry import GpuTelemetry, NodeTelemetryPulse
from hexaqueue_worker.ports.telemetry import TelemetryEmitterPort


class LocalTelemetryCollector(TelemetryEmitterPort):
    """Host system telemetry collector and pulse emitter.

    Args:
        gpu_telemetry_provider: Optional callable returning a list of GpuTelemetry records.
    """

    def __init__(
        self,
        gpu_telemetry_provider: Callable[[], list[GpuTelemetry]] | None = None,
    ) -> None:
        self._gpu_provider = gpu_telemetry_provider
        self._subscribers: dict[
            str | None, set[asyncio.Queue[NodeTelemetryPulse | None]]
        ] = defaultdict(set)
        self._lock = asyncio.Lock()

    def _read_memory_mb(self) -> tuple[int, int]:
        """Read system total and used memory in megabytes from /proc/meminfo or defaults.

        Returns:
            Tuple of (memory_used_mb, memory_total_mb).
        """
        meminfo_path = Path("/proc/meminfo")
        if meminfo_path.exists():
            try:
                mem_total = 0
                mem_available = 0
                for line in meminfo_path.read_text().splitlines():
                    if line.startswith("MemTotal:"):
                        mem_total = int(line.split()[1]) // 1024
                    elif line.startswith("MemAvailable:"):
                        mem_available = int(line.split()[1]) // 1024
                if mem_total > 0:
                    mem_used = max(0, mem_total - mem_available)
                    return mem_used, mem_total
            except Exception:
                pass
        return 2048, 8192

    def _read_scratch_mb(self, path_str: str | None) -> tuple[int, int]:
        """Read scratch volume total and used space in megabytes.

        Args:
            path_str: Scratch directory path to inspect.

        Returns:
            Tuple of (scratch_used_mb, scratch_total_mb).
        """
        target = path_str if path_str and Path(path_str).exists() else "/tmp"
        try:
            stat = os.statvfs(target)
            total_mb = (stat.f_blocks * stat.f_frsize) // (1024 * 1024)
            free_mb = (stat.f_bfree * stat.f_frsize) // (1024 * 1024)
            used_mb = max(0, total_mb - free_mb)
            return used_mb, max(1, total_mb)
        except Exception:
            return 1024, 10240

    def collect_pulse(
        self,
        worker_id: str,
        active_jobs: int = 0,
        scratch_dir: str | None = None,
    ) -> NodeTelemetryPulse:
        """Collect host system metrics into a NodeTelemetryPulse snapshot.

        Args:
            worker_id: Unique worker identifier.
            active_jobs: Current number of running jobs.
            scratch_dir: Optional scratch volume directory path.

        Returns:
            Populated NodeTelemetryPulse.
        """
        try:
            load_avg = os.getloadavg()
        except (AttributeError, OSError):
            load_avg = (0.0, 0.0, 0.0)

        cpu_count = os.cpu_count() or 1
        cpu_pct = min(100.0, round((load_avg[0] / cpu_count) * 100.0, 2))

        mem_used, mem_total = self._read_memory_mb()
        scratch_used, scratch_total = self._read_scratch_mb(scratch_dir)

        gpus: list[GpuTelemetry] = []
        if callable(self._gpu_provider):
            try:
                gpus = self._gpu_provider()
            except Exception:
                gpus = []

        return NodeTelemetryPulse(
            worker_id=worker_id,
            active_jobs=active_jobs,
            cpu_utilization_pct=cpu_pct,
            load_average=load_avg,
            memory_used_mb=mem_used,
            memory_total_mb=mem_total,
            scratch_used_mb=scratch_used,
            scratch_total_mb=scratch_total,
            gpu_metrics=gpus,
        )

    async def emit_pulse(self, pulse: NodeTelemetryPulse) -> None:
        """Broadcast a telemetry pulse to all matching subscriber queues.

        Args:
            pulse: NodeTelemetryPulse instance.
        """
        async with self._lock:
            targeted = set(self._subscribers.get(pulse.worker_id, set()))
            global_subs = set(self._subscribers.get(None, set()))
            all_subs = targeted | global_subs

        for q in all_subs:
            try:
                q.put_nowait(pulse)
            except asyncio.QueueFull:
                try:
                    _ = q.get_nowait()
                    q.put_nowait(pulse)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    async def subscribe_pulses(
        self, worker_id: str | None = None
    ) -> AsyncIterator[NodeTelemetryPulse]:
        """Subscribe to live telemetry pulses.

        Args:
            worker_id: Optional worker identifier filter.

        Yields:
            NodeTelemetryPulse instances.
        """
        sub_queue: asyncio.Queue[NodeTelemetryPulse | None] = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers[worker_id].add(sub_queue)

        try:
            while True:
                pulse = await sub_queue.get()
                if pulse is None:
                    break
                yield pulse
        finally:
            async with self._lock:
                self._subscribers[worker_id].discard(sub_queue)
                if not self._subscribers[worker_id]:
                    self._subscribers.pop(worker_id, None)

    async def close(self) -> None:
        """Close collector and notify all active subscribers."""
        async with self._lock:
            for subs in self._subscribers.values():
                for q in subs:
                    with contextlib.suppress(Exception):
                        q.put_nowait(None)
            self._subscribers.clear()


__all__ = [
    "LocalTelemetryCollector",
]
