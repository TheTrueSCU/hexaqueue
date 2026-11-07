"""Test worker adapters package exports."""

import hexaqueue_worker.adapters


def test_worker_adapters_exports() -> None:
    """Verify adapters package exports."""
    has_worker = hasattr(hexaqueue_worker.adapters, "LocalSubprocessWorker")
    assert has_worker is True
    has_agent = hasattr(hexaqueue_worker.adapters, "WorkerAgent")
    assert has_agent is True
    has_cfg = hasattr(hexaqueue_worker.adapters, "WorkerAgentConfig")
    assert has_cfg is True
