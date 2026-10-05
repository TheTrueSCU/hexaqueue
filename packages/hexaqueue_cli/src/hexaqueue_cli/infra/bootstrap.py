"""Bootstrap lifecycle handler for hexaqueue-cli."""

from hexaqueue_core.infra.bootstrap import HexaqueueBootstrapContext
from hexaqueue_core.infra.registries import HexaqueueConfigRegistry
from hexaqueue_core.ports.bootstrap import BootstrapperPort


class CliBootstrapper(BootstrapperPort):
    """Bootstrapper for hexaqueue-cli services and registries."""

    name: str = "cli"
    order: int = 50

    def register_config(self, registry: HexaqueueConfigRegistry) -> None:
        """Register cli configuration models."""

    def configure(self, context: HexaqueueBootstrapContext) -> None:
        """Configure cli services in application DI container."""


__all__ = [
    "CliBootstrapper",
]
