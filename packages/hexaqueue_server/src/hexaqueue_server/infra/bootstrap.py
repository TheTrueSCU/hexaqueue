"""Bootstrap lifecycle handler for hexaqueue-server."""

from hexaqueue_core.infra.bootstrap import HexaqueueBootstrapContext
from hexaqueue_core.infra.registries import HexaqueueConfigRegistry
from hexaqueue_core.ports.bootstrap import BootstrapperPort


class ServerBootstrapper(BootstrapperPort):
    """Bootstrapper for hexaqueue-server services and registries."""

    name: str = "server"
    order: int = 30

    def register_config(self, registry: HexaqueueConfigRegistry) -> None:
        """Register server configuration models."""

    def configure(self, context: HexaqueueBootstrapContext) -> None:
        """Configure server services in application DI container."""


__all__ = [
    "ServerBootstrapper",
]
