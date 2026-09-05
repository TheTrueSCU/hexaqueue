"""Tests for worker domain models."""

from hexaqueue_worker.domain.models import WorkerConfig, WorkerMetrics


def test_worker_config_defaults() -> None:
    """Verify WorkerConfig default fields."""
    cfg = WorkerConfig()
    assert cfg.concurrency == 4
    assert cfg.worker_id == "local-worker"
    assert cfg.grace_period_seconds == 15
    assert cfg.poll_interval_seconds == 0.1
    assert cfg.scratch_base_dir is None


def test_worker_metrics_model() -> None:
    """Verify WorkerMetrics fields."""
    metrics = WorkerMetrics(
        worker_id="worker-1",
        active_jobs=2,
        total_executed=10,
        total_completed=8,
        total_failed=2,
        is_running=True,
    )
    assert metrics.worker_id == "worker-1"
    assert metrics.active_jobs == 2
    assert metrics.total_executed == 10
    assert metrics.total_completed == 8
    assert metrics.total_failed == 2
    assert metrics.is_running is True
