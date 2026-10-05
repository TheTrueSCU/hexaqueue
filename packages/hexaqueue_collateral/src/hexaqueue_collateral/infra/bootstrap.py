"""Bootstrap lifecycle handler for hexaqueue-collateral."""

from hexaqueue_core.infra.bootstrap import HexaqueueBootstrapContext
from hexaqueue_core.infra.registries import HexaqueueConfigRegistry
from hexaqueue_core.ports.bootstrap import BootstrapperPort


class CollateralBootstrapper(BootstrapperPort):
    """Bootstrapper for hexaqueue-collateral services and registries."""

    name: str = "collateral"
    order: int = 20

    def register_config(self, registry: HexaqueueConfigRegistry) -> None:
        """Register collateral configuration models."""

    def configure(self, context: HexaqueueBootstrapContext) -> None:
        """Configure collateral service in application DI container."""


__all__ = [
    "CollateralBootstrapper",
]
