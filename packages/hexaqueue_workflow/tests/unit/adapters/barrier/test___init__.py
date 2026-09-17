"""Tests for barrier adapters package exports."""

import hexaqueue_workflow.adapters.barrier as barrier_pkg


def test_barrier_adapters_exports() -> None:
    """Verify barrier adapters package exports."""
    expected = [
        "GrpcSplitJoinBarrierAdapter",
    ]
    exports = barrier_pkg.__all__
    assert exports == sorted(expected)
