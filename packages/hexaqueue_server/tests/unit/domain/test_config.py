"""Unit tests for ServerConfig, ServerInterfaceConfig, McpConfig, and ServerRole."""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from hexaqueue_core.domain.exceptions import HexaqueueConfigError
from hexaqueue_server.domain.config import (
    McpConfig,
    McpToolConfig,
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
    assert cfg.mcp is True


def test_server_interface_config_role_presets() -> None:
    """Verify ServerInterfaceConfig.for_role generates expected profiles."""
    gateway = ServerInterfaceConfig.for_role(ServerRole.GATEWAY)
    assert gateway.runs is True
    assert gateway.webhooks is True
    assert gateway.collateral is True
    assert gateway.nodes is False
    assert gateway.budget is False
    assert gateway.mcp is False

    worker_api = ServerInterfaceConfig.for_role(ServerRole.WORKER_API)
    assert worker_api.runs is False
    assert worker_api.nodes is True
    assert worker_api.logs is True
    assert worker_api.webhooks is False
    assert worker_api.mcp is False

    analytics = ServerInterfaceConfig.for_role(ServerRole.ANALYTICS)
    assert analytics.budget is True
    assert analytics.cluster is True
    assert analytics.runs is False
    assert analytics.nodes is False
    assert analytics.mcp is False

    mcp = ServerInterfaceConfig.for_role(ServerRole.MCP)
    assert mcp.mcp is True
    assert mcp.runs is False
    assert mcp.jobs is False

    all_role = ServerInterfaceConfig.for_role(ServerRole.ALL)
    assert all_role.mcp is True
    assert all_role.runs is True


def test_server_interface_config_feature_flags() -> None:
    """Verify feature flags and environment variable overrides on ServerInterfaceConfig."""
    cfg = ServerInterfaceConfig()
    # Dict override
    flagged = cfg.apply_feature_flags(flags={"mcp": False, "webhooks": "0"})
    assert flagged.mcp is False
    assert flagged.webhooks is False
    assert flagged.runs is True

    # Environment override
    os.environ["HQ_INTERFACE_MCP"] = "false"
    os.environ["HQ_INTERFACE_RUNS"] = "0"
    try:
        env_flagged = cfg.apply_feature_flags(use_env=True)
        assert env_flagged.mcp is False
        assert env_flagged.runs is False
        assert env_flagged.jobs is True
    finally:
        os.environ.pop("HQ_INTERFACE_MCP", None)
        os.environ.pop("HQ_INTERFACE_RUNS", None)


def test_mcp_tool_config_and_read_only() -> None:
    """Verify McpToolConfig defaults and read-only preset."""
    tools = McpToolConfig()
    assert tools.list_jobs is True
    assert tools.submit_run is True
    assert tools.lease_task is True
    assert tools.get_run_status is True

    ro = McpToolConfig.read_only()
    assert ro.list_jobs is True
    assert ro.submit_run is False
    assert ro.lease_task is False
    assert ro.get_cluster_nodes is True


def test_mcp_config_read_only_and_feature_flags() -> None:
    """Verify McpConfig read-only enforcement and feature flags."""
    mcp_cfg = McpConfig(read_only=True)
    assert mcp_cfg.read_only is True
    assert mcp_cfg.tools.submit_run is False
    assert mcp_cfg.tools.lease_task is False
    assert mcp_cfg.tools.list_jobs is True

    # Feature flags dict
    flagged = mcp_cfg.apply_feature_flags(
        flags={"mcp.enabled": False, "mcp.read_only": False}
    )
    assert flagged.enabled is False

    # Environment variables
    os.environ["HQ_MCP_ENABLED"] = "false"
    os.environ["HQ_MCP_READ_ONLY"] = "true"
    os.environ["HQ_MCP_AUTH_TOKEN"] = "secret-token-xyz"
    try:
        env_cfg = McpConfig().apply_feature_flags(use_env=True)
        assert env_cfg.enabled is False
        assert env_cfg.read_only is True
        assert env_cfg.auth_token == "secret-token-xyz"
        assert env_cfg.tools.submit_run is False
    finally:
        os.environ.pop("HQ_MCP_ENABLED", None)
        os.environ.pop("HQ_MCP_READ_ONLY", None)
        os.environ.pop("HQ_MCP_AUTH_TOKEN", None)


def test_server_config_defaults_and_role_application() -> None:
    """Verify ServerConfig default values and automatic role preset application."""
    default_cfg = ServerConfig()
    assert default_cfg.engine == "uvicorn"
    assert default_cfg.host == "0.0.0.0"
    assert default_cfg.port == 8000
    assert default_cfg.role == ServerRole.ALL
    assert default_cfg.interfaces.runs is True
    assert default_cfg.interfaces.mcp is True
    assert default_cfg.mcp.enabled is True

    gateway_cfg = ServerConfig(role=ServerRole.GATEWAY)
    assert gateway_cfg.interfaces.webhooks is True
    assert gateway_cfg.interfaces.nodes is False
    assert gateway_cfg.interfaces.mcp is False

    custom_cfg = ServerConfig(
        role=ServerRole.CUSTOM,
        interfaces=ServerInterfaceConfig(runs=True, jobs=False, webhooks=False),
    )
    assert custom_cfg.interfaces.runs is True
    assert custom_cfg.interfaces.jobs is False


def test_server_config_load_from_toml(tmp_path: Path) -> None:
    """Verify ServerConfig.load_from_toml parses valid TOML and applies overrides."""
    toml_file = tmp_path / "test_server.toml"
    toml_content = """
[server]
host = "127.0.0.1"
port = 9000
engine = "granian"
role = "custom"

[server.interfaces]
runs = false
jobs = true
mcp = true
webhooks = false

[server.mcp]
path_prefix = "/ai-mcp"
read_only = true
auth_token = "mcp-secret"
"""
    toml_file.write_text(toml_content.strip())

    cfg = ServerConfig.load_from_toml(toml_file)
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 9000
    assert cfg.engine == "granian"
    assert cfg.role == ServerRole.CUSTOM
    assert cfg.interfaces.runs is False
    assert cfg.interfaces.jobs is True
    assert cfg.interfaces.mcp is True
    assert cfg.interfaces.webhooks is False
    assert cfg.mcp.path_prefix == "/ai-mcp"
    assert cfg.mcp.read_only is True
    assert cfg.mcp.auth_token == "mcp-secret"
    assert cfg.mcp.tools.submit_run is False

    # Role override
    overridden = ServerConfig.load_from_toml(
        toml_file, role_override=ServerRole.GATEWAY
    )
    assert overridden.role == ServerRole.GATEWAY
    assert overridden.interfaces.webhooks is True
    assert overridden.interfaces.mcp is False

    # Non-existent file
    with pytest.raises(HexaqueueConfigError):
        ServerConfig.load_from_toml(tmp_path / "non_existent.toml")


def test_server_config_validation() -> None:
    """Verify ServerConfig rejects invalid ports."""
    with pytest.raises(ValidationError):
        ServerConfig(port=0)

    with pytest.raises(ValidationError):
        ServerConfig(port=70000)


def test_parse_flag_bool_variants() -> None:
    """Verify _parse_flag_bool handles int, float, bool, strings, and unrecognized inputs."""
    from hexaqueue_server.domain.config import _parse_flag_bool

    assert _parse_flag_bool(True) is True
    assert _parse_flag_bool(False) is False
    assert _parse_flag_bool(1) is True
    assert _parse_flag_bool(0) is False
    assert _parse_flag_bool(1.5) is True
    assert _parse_flag_bool("yes") is True
    assert _parse_flag_bool("on") is True
    assert _parse_flag_bool("enabled") is True
    assert _parse_flag_bool("no") is False
    assert _parse_flag_bool("off") is False
    assert _parse_flag_bool("disabled") is False
    assert _parse_flag_bool("maybe") is None
    assert _parse_flag_bool(None) is None
