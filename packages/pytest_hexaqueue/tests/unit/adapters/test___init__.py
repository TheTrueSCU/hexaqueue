"""Tests for adapters package exports."""

import pytest_hexaqueue.adapters as adapters


def test_adapters_exports() -> None:
    """Verify adapters exports."""
    exports = dir(adapters)
    assert "RoundRobinTestSlicer" in exports
    assert "FileContiguousTestSlicer" in exports
    assert "HexaqueueTestDispatchClient" in exports
    assert "InMemoryTestDispatchClient" in exports
    assert "LocalSliceRunner" in exports
