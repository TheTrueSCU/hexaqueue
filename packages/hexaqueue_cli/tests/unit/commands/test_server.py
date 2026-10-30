"""Unit tests for 'hq server' CLI commands."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from hexaqueue_cli.main import app
from hexaqueue_server.domain.config import ServerRole

runner = CliRunner()


def test_server_start_default_invocation() -> None:
    """Verify 'hq server start' invokes run_hexaqueue_server with defaults."""
    with patch("hexaqueue_cli.commands.server.run_hexaqueue_server") as mock_run:
        result = runner.invoke(app, ["server", "start"])
        assert result.exit_code == 0
        assert mock_run.called
        config = mock_run.call_args.kwargs["config"]
        assert config.engine == "uvicorn"
        assert config.role == ServerRole.ALL
        assert config.port == 8000


def test_server_start_role_and_engine_flags() -> None:
    """Verify 'hq server start' sets role and engine flags."""
    with patch("hexaqueue_cli.commands.server.run_hexaqueue_server") as mock_run:
        result = runner.invoke(
            app,
            [
                "server",
                "start",
                "--role",
                "gateway",
                "--engine",
                "granian",
                "--port",
                "8080",
            ],
        )
        assert result.exit_code == 0
        assert mock_run.called
        config = mock_run.call_args.kwargs["config"]
        assert config.role == ServerRole.GATEWAY
        assert config.engine == "granian"
        assert config.port == 8080
        assert config.interfaces.webhooks is True
        assert config.interfaces.nodes is False


def test_server_start_custom_interfaces() -> None:
    """Verify 'hq server start --interfaces' configures custom interface toggles."""
    with patch("hexaqueue_cli.commands.server.run_hexaqueue_server") as mock_run:
        result = runner.invoke(
            app, ["server", "start", "--interfaces", "runs,webhooks"]
        )
        assert result.exit_code == 0
        assert mock_run.called
        config = mock_run.call_args.kwargs["config"]
        assert config.role == ServerRole.CUSTOM
        assert config.interfaces.runs is True
        assert config.interfaces.webhooks is True
        assert config.interfaces.nodes is False
        assert config.interfaces.budget is False


def test_server_start_invalid_role() -> None:
    """Verify 'hq server start --role invalid' exits with error code 1."""
    result = runner.invoke(app, ["server", "start", "--role", "nonexistent"])
    assert result.exit_code == 1
    assert "Invalid server role" in result.output


def test_server_start_mcp_toggle_flags() -> None:
    """Verify --mcp and --no-mcp flags toggle MCP interface independently of role."""
    with patch("hexaqueue_cli.commands.server.run_hexaqueue_server") as mock_run:
        # Enable MCP on gateway (mix-and-match)
        res_enable = runner.invoke(
            app, ["server", "start", "--role", "gateway", "--mcp"]
        )
        assert res_enable.exit_code == 0
        cfg_enabled = mock_run.call_args.kwargs["config"]
        assert cfg_enabled.role == ServerRole.GATEWAY
        assert cfg_enabled.interfaces.mcp is True
        assert cfg_enabled.mcp.enabled is True

        # Disable MCP on all role
        res_disable = runner.invoke(app, ["server", "start", "--no-mcp"])
        assert res_disable.exit_code == 0
        cfg_disabled = mock_run.call_args.kwargs["config"]
        assert cfg_disabled.interfaces.mcp is False
        assert cfg_disabled.mcp.enabled is False


def test_server_start_config_file(tmp_path: Path) -> None:
    """Verify 'hq server start --config' parses TOML configuration."""
    cfg_file = tmp_path / "hq_server.toml"
    cfg_file.write_text(
        """
[server]
host = "10.0.0.1"
port = 7070
role = "custom"

[server.interfaces]
runs = false
jobs = true
mcp = true
"""
    )
    with patch("hexaqueue_cli.commands.server.run_hexaqueue_server") as mock_run:
        res = runner.invoke(app, ["server", "start", "--config", str(cfg_file)])
        assert res.exit_code == 0
        cfg = mock_run.call_args.kwargs["config"]
        assert cfg.host == "10.0.0.1"
        assert cfg.port == 7070
        assert cfg.role == ServerRole.CUSTOM
        assert cfg.interfaces.runs is False
        assert cfg.interfaces.jobs is True
        assert cfg.interfaces.mcp is True


def test_server_start_runner_exception_handling() -> None:
    """Verify runner exceptions exit with error code 1."""
    with patch(
        "hexaqueue_cli.commands.server.run_hexaqueue_server",
        side_effect=RuntimeError("bind failure"),
    ):
        res = runner.invoke(app, ["server", "start"])
        assert res.exit_code == 1
        assert "Failed to start server" in res.output


def test_server_start_config_load_error(tmp_path: Path) -> None:
    """Verify corrupted config file exits with error code 1."""
    corrupt_file = tmp_path / "bad.toml"
    corrupt_file.write_text("not a valid [ [ toml")
    res = runner.invoke(app, ["server", "start", "--config", str(corrupt_file)])
    assert res.exit_code == 1
    assert "Configuration error" in res.output
