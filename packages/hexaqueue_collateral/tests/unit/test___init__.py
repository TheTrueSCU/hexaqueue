"""Tests for hexaqueue_collateral root exports."""

import hexaqueue_collateral


def test_hexaqueue_collateral_root_exports() -> None:
    """Verify collateral exports."""
    assert hasattr(hexaqueue_collateral, "adapters")
    assert hasattr(hexaqueue_collateral, "domain")
    assert hasattr(hexaqueue_collateral, "infra")
    assert hasattr(hexaqueue_collateral, "ports")
