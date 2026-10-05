"""Tests for core configuration models."""

import pytest
from pydantic import BaseModel

from hexaqueue_core.domain.config import (
    CspProvider,
    ExecutionMode,
    HexaqueueConfig,
    HexaqueueConfigError,
    HexaqueueCoreConfig,
)


class SubsystemConfig(BaseModel):
    storage_root: str = "/tmp/storage"


def test_core_config_defaults() -> None:
    """Verify HexaqueueCoreConfig defaults."""
    config = HexaqueueCoreConfig()
    assert config.cluster_id == "hq-default-cluster"
    assert config.mode == ExecutionMode.DEVELOPMENT
    assert config.csp_provider == CspProvider.ONPREM
    assert config.free_tier.max_cpus == 2


def test_hexaqueue_config_container() -> None:
    """Verify HexaqueueConfig container and typed section retrieval."""
    core = HexaqueueCoreConfig()
    subsystem = SubsystemConfig()
    config = HexaqueueConfig(core=core, sections={"subsystem": subsystem})

    assert config.core.cluster_id == "hq-default-cluster"
    retrieved = config.get_section("subsystem", SubsystemConfig)
    assert retrieved.storage_root == "/tmp/storage"


def test_hexaqueue_config_missing_section() -> None:
    """Verify get_section raises HexaqueueConfigError on missing section."""
    core = HexaqueueCoreConfig()
    config = HexaqueueConfig(core=core, sections={})

    with pytest.raises(HexaqueueConfigError):
        config.get_section("nonexistent", SubsystemConfig)
