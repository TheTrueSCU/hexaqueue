"""Tests for HexaqueueConfigRegistry."""

from pathlib import Path

import pytest
from pydantic import BaseModel

from hexaqueue_core.domain.exceptions import HexaqueueConfigError
from hexaqueue_core.infra.registries import HexaqueueConfigRegistry


class SampleSectionConfig(BaseModel):
    max_retries: int = 3


def test_config_registry_registration() -> None:
    """Verify registration and schema tracking."""
    registry = HexaqueueConfigRegistry()
    registry.register(SampleSectionConfig)
    assert len(registry.all) > 0


def test_config_registry_missing_file_raises(tmp_path: Path) -> None:
    """Verify load_config_toml raises HexaqueueConfigError when file does not exist."""
    registry = HexaqueueConfigRegistry()
    missing_file = tmp_path / "nonexistent.toml"
    with pytest.raises(HexaqueueConfigError, match="Configuration file not found"):
        registry.load_config_toml(missing_file)


def test_config_registry_load_valid_toml(tmp_path: Path) -> None:
    """Verify parsing TOML configuration file."""
    registry = HexaqueueConfigRegistry()
    cfg_file = tmp_path / "hexaqueue.toml"
    cfg_file.write_text("""
[hexaqueue]
cluster_id = "test-cluster"
mode = "FREE_TIER"
""")
    config = registry.load_config_toml(cfg_file)
    assert config.core.cluster_id == "test-cluster"
    assert config.core.mode == "FREE_TIER"


def test_config_registry_all_sections_load(tmp_path: Path) -> None:
    """Verify TOML loading populates registered subsystem sections."""
    registry = HexaqueueConfigRegistry()
    registry.register(SampleSectionConfig)
    cfg_file = tmp_path / "hexaqueue.toml"
    cfg_file.write_text("""
[hexaqueue]
cluster_id = "test-cluster"

[sample_section_config]
max_retries = 5
""")
    config = registry.load_config_toml(cfg_file)
    assert config.core.cluster_id == "test-cluster"
