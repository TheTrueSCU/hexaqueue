"""Unit tests for collateral bootstrapper."""

from hexaqueue_collateral.infra.bootstrap import CollateralBootstrapper


def test_collateral_bootstrapper_attributes():
    """Verify CollateralBootstrapper lifecycle attributes."""
    bootstrapper = CollateralBootstrapper()
    assert bootstrapper.name == "collateral"
    assert bootstrapper.order == 20
    assert hasattr(bootstrapper, "register_config")
    assert hasattr(bootstrapper, "configure")
