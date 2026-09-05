"""Tests for hexaqueue_core root exports."""

import hexaqueue_core


def test_hexaqueue_core_root_exports() -> None:
    """Verify core exports."""
    assert hasattr(hexaqueue_core, "adapters")
    assert hasattr(hexaqueue_core, "domain")
    assert hasattr(hexaqueue_core, "infra")
    assert hasattr(hexaqueue_core, "ports")
    assert hasattr(hexaqueue_core, "testing")
    assert hasattr(hexaqueue_core, "utils")
