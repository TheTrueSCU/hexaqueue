"""Tests for CliBootstrapper."""

from rodi import Container

from hexaqueue_cli.infra.bootstrap import CliBootstrapper
from hexaqueue_core.infra.bootstrap import HexaqueueBootstrapContext
from hexaqueue_core.infra.registries import HexaqueueConfigRegistry


def test_cli_bootstrapper() -> None:
    """Verify bootstrapper registration and configuration."""
    bootstrapper = CliBootstrapper()
    assert bootstrapper.name == "cli"
    assert bootstrapper.order == 50

    registry = HexaqueueConfigRegistry()
    bootstrapper.register_config(registry)

    ctx = HexaqueueBootstrapContext(
        container=Container(),
        config=None,
        config_registry=registry,
    )
    bootstrapper.configure(ctx)
