"""Tests for WorkerBootstrapper."""

from hexastack_core.infra.container import create_container

from hexaqueue_core.infra.bootstrap import HexaqueueBootstrapContext
from hexaqueue_core.infra.registries import HexaqueueConfigRegistry
from hexaqueue_worker.infra.bootstrap import WorkerBootstrapper


def test_worker_bootstrapper() -> None:
    """Verify bootstrapper registration and configuration."""
    bootstrapper = WorkerBootstrapper()
    assert bootstrapper.name == "worker"
    assert bootstrapper.order == 40

    registry = HexaqueueConfigRegistry()
    bootstrapper.register_config(registry)

    ctx = HexaqueueBootstrapContext(
        container=create_container(),
        config=None,
        config_registry=registry,
    )
    bootstrapper.configure(ctx)
