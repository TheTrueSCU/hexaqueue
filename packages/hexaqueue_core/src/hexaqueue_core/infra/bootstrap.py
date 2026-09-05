"""Bootstrapping orchestrator and context extending Hexastack DI foundation.

Notes/Architectural Intent:
    Coordinates multi-phase bootstrap for Hexaqueue applications.
    Integrates with rodi Container, Hexastack CQRS, event buses, and
    modular BootstrapperPort extensions.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hexastack_core.ports.bootstrap import BootstrapperPort
from rodi import Container

from hexaqueue_core.domain.config import (
    HexaqueueConfig,
)
from hexaqueue_core.infra.registries import (
    HexaqueueConfigRegistry,
)


@dataclass
class HexaqueueBootstrapContext:
    """Runtime context passed across Hexaqueue subsystem bootstrappers.

    Args:
        container: The rodi dependency injection container.
        config: Loaded HexaqueueConfig instance (or None if unconfigured).
        config_registry: HexaqueueConfigRegistry instance.
        properties: Shared runtime properties map.
    """

    container: Container
    config: HexaqueueConfig | None
    config_registry: HexaqueueConfigRegistry
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HexaqueueBootstrapResult:
    """Encapsulates the complete bootstrapped runtime state."""

    container: Container
    config: HexaqueueConfig | None
    config_registry: HexaqueueConfigRegistry
    bootstrappers: list[BootstrapperPort]
    properties: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a bootstrap property value."""
        return self.properties.get(key, default)


def bootstrap_hexaqueue(
    config_path: str | Path | None = None,
    bootstrappers: list[BootstrapperPort] | None = None,
    container: Container | None = None,
    configure_container: Callable[[Container], None] | None = None,
) -> HexaqueueBootstrapResult:
    """Bootstrap a complete Hexaqueue runtime with dependency injection and configuration.

    Args:
        config_path: Optional path to a hexaqueue.toml configuration file.
        bootstrappers: Optional explicit list of BootstrapperPort instances.
        container: Optional pre-configured rodi Container.
        configure_container: Optional custom container binding hook.

    Returns:
        HexaqueueBootstrapResult containing initialized container and models.
    """
    di = container or Container()
    sorted_bootstrappers = sorted(
        bootstrappers or [], key=lambda b: getattr(b, "order", 50)
    )

    # Phase 1: Register config schemas
    config_reg = HexaqueueConfigRegistry()
    for b in sorted_bootstrappers:
        b.register_config(config_reg)

    di.add_instance(config_reg, declared_class=HexaqueueConfigRegistry)

    # Phase 2: Load TOML configuration if provided
    loaded_config: HexaqueueConfig | None = None
    if config_path and Path(config_path).exists():
        loaded_config = config_reg.load_config_toml(config_path)
        di.add_instance(loaded_config, declared_class=HexaqueueConfig)
        di.add_instance(loaded_config.core, declared_class=type(loaded_config.core))

    # Phase 3: Configure subsystems
    context = HexaqueueBootstrapContext(
        container=di,
        config=loaded_config,
        config_registry=config_reg,
        properties={},
    )

    for b in sorted_bootstrappers:
        b.configure(context)

    # Phase 4: User customization hook
    if configure_container is not None:
        configure_container(di)

    return HexaqueueBootstrapResult(
        container=di,
        config=loaded_config,
        config_registry=config_reg,
        bootstrappers=sorted_bootstrappers,
        properties=context.properties,
    )


__all__ = [
    "bootstrap_hexaqueue",
    "HexaqueueBootstrapContext",
    "HexaqueueBootstrapResult",
]
