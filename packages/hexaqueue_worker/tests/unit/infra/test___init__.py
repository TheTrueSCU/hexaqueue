"""Test worker infra package exports."""

import hexaqueue_worker.infra


def test_worker_infra_exports() -> None:
    """Verify infra package exports."""
    assert hasattr(hexaqueue_worker.infra, "WorkerBootstrapper")
