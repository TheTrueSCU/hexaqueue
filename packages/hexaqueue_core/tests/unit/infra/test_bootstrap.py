"""Tests for Hexaqueue core bootstrap orchestrator."""

from pathlib import Path

from rodi import Container

from hexaqueue_core.infra.bootstrap import (
    HexaqueueBootstrapContext,
    HexaqueueBootstrapResult,
    bootstrap_hexaqueue,
)
from hexaqueue_core.infra.registries import HexaqueueConfigRegistry
from hexaqueue_core.ports.bootstrap import BootstrapperPort


class DummyBootstrapper(BootstrapperPort):
    """Test bootstrapper."""

    name: str = "dummy"
    order: int = 10

    def register_config(self, registry: HexaqueueConfigRegistry) -> None:
        pass

    def configure(self, context: HexaqueueBootstrapContext) -> None:
        context.properties["dummy_loaded"] = True


def test_bootstrap_hexaqueue_defaults(tmp_path: Path) -> None:
    """Verify bootstrap_hexaqueue with defaults and configuration file."""
    cfg_file = tmp_path / "hexaqueue.toml"
    cfg_file.write_text("""
[hexaqueue]
cluster_id = "test-cluster"
""")
    dummy = DummyBootstrapper()
    custom_called = False

    def custom_hook(container: Container) -> None:
        nonlocal custom_called
        custom_called = True

    result = bootstrap_hexaqueue(
        config_path=cfg_file,
        bootstrappers=[dummy],
        configure_container=custom_hook,
    )

    assert isinstance(result, HexaqueueBootstrapResult)
    assert result.config is not None
    assert result.config.core.cluster_id == "test-cluster"
    assert result.get("dummy_loaded") is True
    assert result.get("nonexistent", "default_val") == "default_val"
    assert custom_called is True


def test_bootstrap_hexaqueue_without_config() -> None:
    """Verify bootstrap_hexaqueue with no config file."""
    result = bootstrap_hexaqueue()
    assert isinstance(result, HexaqueueBootstrapResult)
    assert result.config is None
