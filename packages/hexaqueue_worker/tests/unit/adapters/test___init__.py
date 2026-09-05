"""Test worker adapters package exports."""

import hexaqueue_worker.adapters


def test_worker_adapters_exports() -> None:
    """Verify adapters package exports."""
    assert hasattr(hexaqueue_worker.adapters, "LocalSubprocessWorker")
