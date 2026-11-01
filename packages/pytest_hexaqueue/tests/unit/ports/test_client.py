"""Unit tests verifying abstractness of HexaqueueTestDispatchPort."""

import inspect

from pytest_hexaqueue.ports.client import HexaqueueTestDispatchPort


def test_dispatch_port_is_abstract() -> None:
    """Verify HexaqueueTestDispatchPort is an abstract ABC."""
    assert inspect.isabstract(HexaqueueTestDispatchPort)
