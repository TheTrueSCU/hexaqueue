"""Tests for ServerBootstrapper."""

from rodi import Container

from hexaqueue_core.infra.bootstrap import HexaqueueBootstrapContext
from hexaqueue_core.infra.registries import HexaqueueConfigRegistry
from hexaqueue_server.infra.bootstrap import ServerBootstrapper


def test_server_bootstrapper() -> None:
    """Verify ServerBootstrapper initialization and interface methods."""
    bootstrapper = ServerBootstrapper()
    assert bootstrapper.name == "server"
    assert bootstrapper.order == 30

    registry = HexaqueueConfigRegistry()
    bootstrapper.register_config(registry)

    context = HexaqueueBootstrapContext(
        container=Container(),
        config=None,
        config_registry=registry,
    )
    bootstrapper.configure(context)
