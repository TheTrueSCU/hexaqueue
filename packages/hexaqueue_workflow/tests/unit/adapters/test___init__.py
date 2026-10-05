"""Tests for adapters package exports."""

import hexaqueue_workflow.adapters as adapters_pkg


def test_adapters_exports() -> None:
    """Verify all expected adapters are exported."""
    expected = [
        "GrpcSplitJoinBarrierAdapter",
        "HexaqueueDistributedEngine",
        "StoragePortArtifactStagingAdapter",
    ]
    exports = adapters_pkg.__all__
    assert exports == sorted(expected)
