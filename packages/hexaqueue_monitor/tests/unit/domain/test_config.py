"""Unit tests for monitor configuration models."""

from hexaqueue_monitor.domain.config import MonitorConfig


def test_monitor_config_defaults() -> None:
    """Verify default timeout and interval thresholds in MonitorConfig."""
    cfg = MonitorConfig()
    assert cfg.heartbeat_interval_seconds == 10.0
    assert cfg.unhealthy_threshold_seconds == 30.0
    assert cfg.dead_threshold_seconds == 60.0
    assert cfg.reaper_interval_seconds == 15.0
    assert cfg.reservation_expiry_seconds == 3600.0


def test_monitor_config_custom_values() -> None:
    """Verify custom MonitorConfig parameters."""
    cfg = MonitorConfig(
        dead_threshold_seconds=120.0,
        heartbeat_interval_seconds=5.0,
        reaper_interval_seconds=10.0,
        reservation_expiry_seconds=7200.0,
        unhealthy_threshold_seconds=45.0,
    )
    assert cfg.dead_threshold_seconds == 120.0
    assert cfg.heartbeat_interval_seconds == 5.0
    assert cfg.reaper_interval_seconds == 10.0
    assert cfg.reservation_expiry_seconds == 7200.0
    assert cfg.unhealthy_threshold_seconds == 45.0


__all__ = [
    "test_monitor_config_custom_values",
    "test_monitor_config_defaults",
]
