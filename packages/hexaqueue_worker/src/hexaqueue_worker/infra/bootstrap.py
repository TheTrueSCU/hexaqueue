"""Bootstrap lifecycle handler for hexaqueue-worker."""

from hexaqueue_core.infra.bootstrap import HexaqueueBootstrapContext
from hexaqueue_core.infra.registries import HexaqueueConfigRegistry
from hexaqueue_core.ports.bootstrap import BootstrapperPort


class WorkerBootstrapper(BootstrapperPort):
    """Bootstrapper for hexaqueue-worker services and registries."""

    name: str = "worker"
    order: int = 40

    def register_config(self, registry: HexaqueueConfigRegistry) -> None:
        """Register worker configuration models."""

    def configure(self, context: HexaqueueBootstrapContext) -> None:
        """Configure worker services in application DI container."""


__all__ = [
    "WorkerBootstrapper",
]
