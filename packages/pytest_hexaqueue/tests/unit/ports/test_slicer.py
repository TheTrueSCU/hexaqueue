"""Unit tests verifying abstractness of TestSlicerPort."""

import inspect

from pytest_hexaqueue.ports.slicer import TestSlicerPort


def test_slicer_port_is_abstract() -> None:
    """Verify TestSlicerPort is an abstract ABC."""
    assert inspect.isabstract(TestSlicerPort)
