"""Test worker domain package exports."""

import hexaqueue_worker.domain


def test_worker_domain_exports() -> None:
    """Verify domain package exports."""
    assert hasattr(hexaqueue_worker.domain, "WorkerConfig")
    assert hasattr(hexaqueue_worker.domain, "WorkerMetrics")
