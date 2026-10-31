"""Unit tests for scanner daemon bootstrap factory."""

from hexaqueue_scanner.domain.config import ScannerConfig
from hexaqueue_scanner.infra.bootstrap import create_scanner_daemon


def test_create_scanner_daemon_defaults() -> None:
    """Verify default factory wiring."""
    daemon = create_scanner_daemon()
    running = daemon.is_running()
    assert running is False

    metrics = daemon.get_metrics()
    total = metrics.total_scans
    assert total == 0


def test_create_scanner_daemon_with_custom_config() -> None:
    """Verify custom config and poll interval passed to daemon."""
    cfg = ScannerConfig(quarantine_on_threat=False)
    daemon = create_scanner_daemon(config=cfg, poll_interval_seconds=0.1)
    metrics = daemon.get_metrics()
    total = metrics.total_scans
    assert total == 0
