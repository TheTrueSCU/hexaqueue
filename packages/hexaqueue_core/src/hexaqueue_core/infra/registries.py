"""Registry implementations extending Hexastack generic registries.

Notes/Architectural Intent:
    Specializes Hexastack's ConfigRegistry and GenericTypeRegistry for
    Hexaqueue configuration files (hexaqueue.toml) and runtime plugins.
"""

import tomllib
from pathlib import Path

from hexastack_core.infra.registries.config import (
    ConfigRegistry as HexastackConfigRegistry,
)
from hexastack_core.infra.registries.generic import (
    GenericHandlerRegistry,
    GenericHandlerRegistryError,
    GenericTypeRegistry,
    GenericTypeRegistryError,
)
from pydantic import BaseModel

from hexaqueue_core.domain.config import (
    HexaqueueConfig,
    HexaqueueCoreConfig,
)
from hexaqueue_core.domain.exceptions import HexaqueueConfigError


class HexaqueueConfigRegistry(HexastackConfigRegistry):
    """Configuration registry specializing TOML loading for HexaqueueConfig.

    Notes/Architectural Intent:
        Parses hexaqueue.toml files into HexaqueueCoreConfig and registered
        subsystem sections with strict validation.
    """

    def __init__(self) -> None:
        """Initialize registry with HexaqueueCoreConfig schema."""
        super().__init__()
        self._core_schema: type[HexaqueueCoreConfig] = HexaqueueCoreConfig

    def load_config_toml(
        self, raw_file_path: str | Path = "hexaqueue.toml"
    ) -> HexaqueueConfig:
        """Parse a TOML file into a typed HexaqueueConfig container.

        Args:
            raw_file_path: Path to TOML configuration file. Defaults to "hexaqueue.toml".

        Returns:
            HexaqueueConfig instance.

        Raises:
            HexaqueueConfigError: If file is missing, syntax is invalid, or validation fails.
        """
        file_path = Path(raw_file_path)
        if not file_path.exists():
            msg = f"Configuration file not found at '{file_path}'"
            raise HexaqueueConfigError(msg)

        try:
            with file_path.open("rb") as f:
                raw_data = tomllib.load(f)

            core_data = raw_data.get("hexaqueue", raw_data.get("hexastack", {}))
            core_config = self._core_schema(**core_data)

            section_configs: dict[str, BaseModel] = {}
            for name, schema in self.all.items():
                section_data = raw_data.get(name, core_data.get(name, {}))
                section_configs[name] = schema(**section_data)

            return HexaqueueConfig(core=core_config, sections=section_configs)
        except Exception as err:
            raise HexaqueueConfigError(f"Failed to load configuration: {err}") from err


__all__ = [
    "GenericHandlerRegistry",
    "GenericHandlerRegistryError",
    "GenericTypeRegistry",
    "GenericTypeRegistryError",
    "HexaqueueConfigRegistry",
]
