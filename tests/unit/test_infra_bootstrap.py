"""Unit tests for Hexaqueue configuration, registries, and bootstrapping."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from pydantic import BaseModel, Field

from hexaqueue_core.domain.config import (
    CspProvider,
    ExecutionMode,
    HexaqueueConfig,
    HexaqueueConfigError,
)
from hexaqueue_core.infra.bootstrap import (
    HexaqueueBootstrapContext,
    bootstrap_hexaqueue,
)
from hexaqueue_core.infra.registries import (
    GenericHandlerRegistry,
    GenericHandlerRegistryError,
    GenericTypeRegistry,
    GenericTypeRegistryError,
    HexaqueueConfigRegistry,
)
from hexaqueue_core.ports.bootstrap import BootstrapperPort


class CustomServerSection(BaseModel):
    """Custom test section."""

    port: int = Field(default=9090)
    worker_timeout_s: int = Field(default=30)


class MockServerBootstrapper(BootstrapperPort):
    """Mock bootstrapper extension."""

    name: str = "mock_server"
    order: int = 10

    def register_config(self, registry: HexaqueueConfigRegistry) -> None:
        """Register CustomServerSection schema."""
        registry.register_config_section("server", CustomServerSection)

    def configure(self, context: HexaqueueBootstrapContext) -> None:
        """Store configured state in context properties."""
        cfg = (
            context.config.get_section("server", CustomServerSection)
            if context.config
            else CustomServerSection()
        )
        context.properties["server_port"] = cfg.port


def test_generic_type_registry():
    """Verify GenericTypeRegistry registration and lookup."""
    reg = GenericTypeRegistry[BaseModel]()
    reg.register_by_name(CustomServerSection, "server")

    assert "server" in reg
    assert reg.get("server") is CustomServerSection

    with pytest.raises(GenericTypeRegistryError):
        reg.get("unregistered")


def test_generic_handler_registry():
    """Verify GenericHandlerRegistry execution and error handling."""
    reg = GenericHandlerRegistry[int, str]()
    reg.register(int, lambda x: f"number_{x}")

    assert reg.handle(42) == "number_42"

    with pytest.raises(GenericHandlerRegistryError):
        reg.handle("invalid_type")


def test_config_registry_toml_parsing():
    """Verify TOML configuration parsing into typed HexaqueueConfig."""
    registry = HexaqueueConfigRegistry()
    registry.register_config_section("server", CustomServerSection)

    with TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "hexaqueue.toml"
        config_file.write_text(
            """
[hexaqueue]
cluster_id = "test-cluster-1"
mode = "FREE_TIER"
csp_provider = "GCP"

[server]
port = 8080
worker_timeout_s = 45
"""
        )

        config = registry.load_config_toml(config_file)
        assert isinstance(config, HexaqueueConfig)
        assert config.core.cluster_id == "test-cluster-1"
        assert config.core.mode == ExecutionMode.FREE_TIER
        assert config.core.csp_provider == CspProvider.GCP

        server_cfg = config.get_section("server", CustomServerSection)
        assert server_cfg.port == 8080
        assert server_cfg.worker_timeout_s == 45


def test_config_registry_missing_file():
    """Verify HexaqueueConfigError raised when config file is missing."""
    registry = HexaqueueConfigRegistry()
    with pytest.raises(HexaqueueConfigError, match="Configuration file not found"):
        registry.load_config_toml("non_existent.toml")


def test_bootstrap_hexaqueue_lifecycle():
    """Verify complete multi-phase bootstrap execution."""
    bootstrapper = MockServerBootstrapper()

    with TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "hexaqueue.toml"
        config_file.write_text(
            """
[hexaqueue]
cluster_id = "prod-us-east"
mode = "PRODUCTION"

[server]
port = 50051
"""
        )

        result = bootstrap_hexaqueue(
            config_path=config_file,
            bootstrappers=[bootstrapper],
        )

        assert result.config is not None
        assert result.config.core.cluster_id == "prod-us-east"
        assert result.get("server_port") == 50051
        assert HexaqueueConfigRegistry in result.container
