"""Unit tests for MonitorDaemon background runner."""

import pytest

from hexaqueue_monitor.adapters.ledger import InMemoryBudgetLedgerAdapter
from hexaqueue_monitor.adapters.local import LocalClusterMonitorAdapter
from hexaqueue_monitor.domain.config import MonitorConfig
from hexaqueue_monitor.domain.models import NodeTelemetryPulse
from hexaqueue_monitor.infra.daemon import MonitorDaemon


@pytest.mark.asyncio
async def test_monitor_daemon_run_once() -> None:
    """Verify synchronous run_once sweep executes dead node detection and stale hold expiry."""
    cfg = MonitorConfig(dead_threshold_seconds=0.0, reservation_expiry_seconds=0.0)
    monitor = LocalClusterMonitorAdapter(config=cfg)
    ledger = InMemoryBudgetLedgerAdapter(initial_balances={"t-1": 100.0})

    # Set up node and hold
    await monitor.record_pulse(
        NodeTelemetryPulse(
            worker_id="worker-sweep-1",
            memory_used_mb=1024,
            memory_total_mb=4096,
            scratch_used_mb=10,
            scratch_total_mb=100,
        )
    )
    hold_id = await ledger.reserve_budget("t-1", "j-1", 20.0)

    daemon = MonitorDaemon(cluster_monitor=monitor, budget_ledger=ledger, config=cfg)
    assert daemon.sweep_count == 0
    assert daemon.is_running is False

    dead_workers, expired_holds = await daemon.run_once()
    assert daemon.sweep_count == 1
    assert "worker-sweep-1" in dead_workers
    assert hold_id in expired_holds


@pytest.mark.asyncio
async def test_monitor_daemon_start_stop() -> None:
    """Verify daemon start and stop lifecycle."""
    cfg = MonitorConfig(reaper_interval_seconds=0.01)
    monitor = LocalClusterMonitorAdapter(config=cfg)
    ledger = InMemoryBudgetLedgerAdapter()
    daemon = MonitorDaemon(cluster_monitor=monitor, budget_ledger=ledger, config=cfg)

    await daemon.start()
    assert daemon.is_running is True

    await daemon.stop()
    assert daemon.is_running is False


__all__ = [
    "test_monitor_daemon_run_once",
    "test_monitor_daemon_start_stop",
]
