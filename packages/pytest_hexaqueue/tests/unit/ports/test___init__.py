"""Tests for ports package exports."""

import pytest_hexaqueue.ports as ports


def test_ports_exports() -> None:
    """Verify ports exports."""
    exports = dir(ports)
    assert "TestSlicerPort" in exports
    assert "HexaqueueTestDispatchPort" in exports
