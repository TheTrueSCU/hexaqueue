"""Unit tests for scanner daemon port interfaces."""

import pytest

from hexaqueue_scanner.domain.models import CompositeScanReport, ScannerMetrics
from hexaqueue_scanner.ports.daemon import ScannerDaemonPort, ScanTaskQueuePort


class DummyTaskQueue(ScanTaskQueuePort):
    """Concrete test implementation of ScanTaskQueuePort."""

    def __init__(self) -> None:
        self.tasks: list[str] = []

    async def enqueue_task(self, collateral_id: str) -> None:
        """Enqueue task."""
        self.tasks.append(collateral_id)

    async def get_next_task(self, timeout_seconds: float = 1.0) -> str | None:
        """Get next task."""
        if self.tasks:
            return self.tasks.pop(0)
        return None

    def queue_size(self) -> int:
        """Return queue size."""
        return len(self.tasks)


class DummyScannerDaemon(ScannerDaemonPort):
    """Concrete test implementation of ScannerDaemonPort."""

    def __init__(self) -> None:
        self._running = False

    async def start(self) -> None:
        """Start daemon."""
        self._running = True

    async def stop(self) -> None:
        """Stop daemon."""
        self._running = False

    async def process_bundle(self, collateral_id: str) -> CompositeScanReport:
        """Process bundle."""
        return CompositeScanReport(
            collateral_id=collateral_id,
            duration_seconds=0.01,
            is_clean=True,
        )

    def get_metrics(self) -> ScannerMetrics:
        """Get metrics."""
        return ScannerMetrics()

    def is_running(self) -> bool:
        """Check if running."""
        return self._running


@pytest.mark.asyncio
async def test_dummy_task_queue_contract() -> None:
    """Verify ScanTaskQueuePort contract implementation."""
    queue = DummyTaskQueue()
    init_size = queue.queue_size()
    assert init_size == 0

    await queue.enqueue_task("col-1")
    size = queue.queue_size()
    assert size == 1

    task = await queue.get_next_task()
    assert task == "col-1"

    empty_task = await queue.get_next_task()
    assert empty_task is None


@pytest.mark.asyncio
async def test_dummy_scanner_daemon_contract() -> None:
    """Verify ScannerDaemonPort contract implementation."""
    daemon = DummyScannerDaemon()
    init_running = daemon.is_running()
    assert init_running is False

    await daemon.start()
    started = daemon.is_running()
    assert started is True

    report = await daemon.process_bundle("col-123")
    cid = report.collateral_id
    assert cid == "col-123"
    clean = report.is_clean
    assert clean is True

    metrics = daemon.get_metrics()
    total = metrics.total_scans
    assert total == 0

    await daemon.stop()
    stopped = daemon.is_running()
    assert stopped is False
