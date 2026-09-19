"""Unit tests for CLI domain models."""

from hexaqueue_cli.domain.models import ClusterStatsReport


def test_cluster_stats_report_defaults() -> None:
    """Verify default fields and timestamps for ClusterStatsReport."""
    report = ClusterStatsReport()
    total_jobs = report.total_jobs
    running_jobs = report.running_jobs
    active_workers = report.active_workers
    assert total_jobs == 0
    assert running_jobs == 0
    assert active_workers == 1
    assert report.timestamp is not None


def test_cluster_stats_report_custom_values() -> None:
    """Verify custom values are correctly retained and validated."""
    report = ClusterStatsReport(
        total_runs=5,
        total_jobs=20,
        running_jobs=4,
        pending_jobs=10,
        blocked_jobs=2,
        completed_jobs=3,
        failed_jobs=1,
        active_workers=2,
    )
    total_runs = report.total_runs
    running_jobs = report.running_jobs
    failed_jobs = report.failed_jobs
    assert total_runs == 5
    assert running_jobs == 4
    assert failed_jobs == 1
