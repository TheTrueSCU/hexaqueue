"""Tests for CollateralBootstrapper."""

from rodi import Container

from hexaqueue_collateral.infra.bootstrap import CollateralBootstrapper
from hexaqueue_core.infra.bootstrap import HexaqueueBootstrapContext
from hexaqueue_core.infra.registries import HexaqueueConfigRegistry


def test_collateral_bootstrapper() -> None:
    """Verify CollateralBootstrapper initialization and interface methods."""
    bootstrapper = CollateralBootstrapper()
    assert bootstrapper.name == "collateral"
    assert bootstrapper.order == 20

    registry = HexaqueueConfigRegistry()
    bootstrapper.register_config(registry)

    context = HexaqueueBootstrapContext(
        container=Container(),
        config=None,
        config_registry=registry,
    )
    bootstrapper.configure(context)
