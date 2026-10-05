"""Test worker root package exports."""

import hexaqueue_worker


def test_worker_package_exports() -> None:
    """Verify package __all__ exports."""
    assert hasattr(hexaqueue_worker, "LocalSubprocessWorker")
    assert hasattr(hexaqueue_worker, "WorkerConfig")
    assert hasattr(hexaqueue_worker, "WorkerDaemonPort")
    assert hasattr(hexaqueue_worker, "WorkerMetrics")
    assert hasattr(hexaqueue_worker, "WorkerBootstrapper")
