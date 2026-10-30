"""Unit tests for ServerConfig, ServerInterfaceConfig, and ServerRole."""

import pytest
from pydantic import ValidationError

from hexaqueue_server.domain.config import (
    ServerConfig,
    ServerInterfaceConfig,
    ServerRole,
)


def test_server_role_enum_values() -> None:
    """Verify ServerRole enumeration members."""
    assert ServerRole.ALL == "all"
    assert ServerRole.GATEWAY == "gateway"
    assert ServerRole.WORKER_API == "worker-api"
    assert ServerRole.ANALYTICS == "analytics"
    assert ServerRole.MCP == "mcp"
    assert ServerRole.CUSTOM == "custom"


def test_server_interface_config_defaults() -> None:
    """Verify ServerInterfaceConfig default enablement flags."""
    cfg = ServerInterfaceConfig()
    assert cfg.runs is True
    assert cfg.jobs is True
    assert cfg.nodes is True
    assert cfg.logs is True
    assert cfg.cluster is True
    assert cfg.collateral is True
    assert cfg.budget is True
    assert cfg.webhooks is True
    assert cfg.mcp is False


def test_server_interface_config_role_presets() -> None:
    """Verify ServerInterfaceConfig.for_role generates expected profiles."""
    gateway = ServerInterfaceConfig.for_role(ServerRole.GATEWAY)
    assert gateway.runs is True
    assert gateway.webhooks is True
    assert gateway.collateral is True
    assert gateway.nodes is False
    assert gateway.budget is False

    worker_api = ServerInterfaceConfig.for_role(ServerRole.WORKER_API)
    assert worker_api.runs is False
    assert worker_api.nodes is True
    assert worker_api.logs is True
    assert worker_api.webhooks is False

    analytics = ServerInterfaceConfig.for_role(ServerRole.ANALYTICS)
    assert analytics.budget is True
    assert analytics.cluster is True
    assert analytics.runs is False
    assert analytics.nodes is False

    mcp = ServerInterfaceConfig.for_role(ServerRole.MCP)
    assert mcp.mcp is True
    assert mcp.runs is True

    all_role = ServerInterfaceConfig.for_role(ServerRole.ALL)
    assert all_role.mcp is True
    assert all_role.runs is True


def test_server_config_defaults_and_role_application() -> None:
    """Verify ServerConfig default values and automatic role preset application."""
    default_cfg = ServerConfig()
    assert default_cfg.engine == "uvicorn"
    assert default_cfg.host == "0.0.0.0"
    assert default_cfg.port == 8000
    assert default_cfg.role == ServerRole.ALL
    assert default_cfg.interfaces.runs is True

    gateway_cfg = ServerConfig(role=ServerRole.GATEWAY)
    assert gateway_cfg.interfaces.webhooks is True
    assert gateway_cfg.interfaces.nodes is False

    custom_cfg = ServerConfig(
        role=ServerRole.CUSTOM,
        interfaces=ServerInterfaceConfig(runs=True, jobs=False, webhooks=False),
    )
    assert custom_cfg.interfaces.runs is True
    assert custom_cfg.interfaces.jobs is False


def test_server_config_validation() -> None:
    """Verify ServerConfig rejects invalid ports."""
    with pytest.raises(ValidationError):
        ServerConfig(port=0)

    with pytest.raises(ValidationError):
        ServerConfig(port=70000)
