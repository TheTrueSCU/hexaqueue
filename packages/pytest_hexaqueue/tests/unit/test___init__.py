"""Tests for pytest_hexaqueue root package exports."""

import importlib

import pytest
import pytest_hexaqueue


def test_root_package_exports() -> None:
    """Verify root package exports are available."""
    # Reload under coverage to trace top-level module code
    importlib.reload(pytest_hexaqueue)

    exports = dir(pytest_hexaqueue)
    assert "RoundRobinTestSlicer" in exports
    assert "FileContiguousTestSlicer" in exports
    assert "HexaqueueTestDispatchClient" in exports
    assert "InMemoryTestDispatchClient" in exports
    assert "TestSliceSpec" in exports
    assert "SliceOutcomeReport" in exports
    assert "WorkspaceDeltaBundle" in exports
    assert "TestItemInfo" in exports
    assert "TestOutcomeItem" in exports
    assert "TestRunSession" in exports
    assert "TestSlicerPort" in exports
    assert "HexaqueueTestDispatchPort" in exports

    # Access lazy symbols
    assert pytest_hexaqueue.RoundRobinTestSlicer is not None
    assert pytest_hexaqueue.FileContiguousTestSlicer is not None
    assert pytest_hexaqueue.HexaqueueTestDispatchClient is not None
    assert pytest_hexaqueue.InMemoryTestDispatchClient is not None
    assert pytest_hexaqueue.TestSliceSpec is not None
    assert pytest_hexaqueue.SliceOutcomeReport is not None
    assert pytest_hexaqueue.WorkspaceDeltaBundle is not None
    assert pytest_hexaqueue.TestItemInfo is not None
    assert pytest_hexaqueue.TestOutcomeItem is not None
    assert pytest_hexaqueue.TestRunSession is not None
    assert pytest_hexaqueue.TestSlicerPort is not None
    assert pytest_hexaqueue.HexaqueueTestDispatchPort is not None

    # Access lazy submodules
    assert pytest_hexaqueue.adapters is not None
    assert pytest_hexaqueue.domain is not None
    assert pytest_hexaqueue.infra is not None
    assert pytest_hexaqueue.ports is not None

    # Unknown symbol raises AttributeError
    with pytest.raises(AttributeError, match="has no attribute 'non_existent'"):
        _ = pytest_hexaqueue.non_existent
