"""Test worker ports package exports."""

import hexaqueue_worker.ports


def test_worker_ports_exports() -> None:
    """Verify ports package exports."""
    assert hasattr(hexaqueue_worker.ports, "WorkerDaemonPort")
