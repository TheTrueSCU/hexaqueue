"""Tests for hexaqueue_server root package exports."""

import hexaqueue_server


def test_hexaqueue_server_exports() -> None:
    """Verify package exposes all expected subpackages."""
    assert hasattr(hexaqueue_server, "adapters")
    assert hasattr(hexaqueue_server, "domain")
    assert hasattr(hexaqueue_server, "infra")
    assert hasattr(hexaqueue_server, "ports")
