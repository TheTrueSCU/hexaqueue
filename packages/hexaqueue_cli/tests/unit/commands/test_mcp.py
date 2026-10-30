"""Unit tests for 'hq mcp' CLI commands."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from hexaqueue_cli.main import app

runner = CliRunner()


def test_hq_mcp_run_invokes_stdio_server() -> None:
    """Verify that 'hq mcp run' invokes the stdio runner."""
    with patch("hexaqueue_cli.commands.mcp.run_mcp_stdio") as mock_stdio:
        result = runner.invoke(app, ["mcp", "run", "--name", "test-mcp-server"])
        res_code = result.exit_code
        assert res_code == 0
        assert mock_stdio.called is True
        _args, kwargs = mock_stdio.call_args
        assert kwargs.get("name") == "test-mcp-server"


def test_hq_mcp_run_read_only_and_tools_options() -> None:
    """Verify --read-only and --tools configure MCP tool constraints."""
    with patch("hexaqueue_cli.commands.mcp.run_mcp_stdio") as mock_stdio:
        result = runner.invoke(
            app, ["mcp", "run", "--read-only", "--tools", "list_jobs,get_run_status"]
        )
        assert result.exit_code == 0
        _args, kwargs = mock_stdio.call_args
        cfg = kwargs.get("config")
        assert cfg is not None
        assert cfg.read_only is True
        assert cfg.tools.list_jobs is True
        assert cfg.tools.get_run_status is True
        assert cfg.tools.submit_run is False
        assert cfg.tools.lease_task is False


def test_hq_mcp_run_config_file(tmp_path: Path) -> None:
    """Verify 'hq mcp run --config' loads TOML configuration."""
    cfg_file = tmp_path / "mcp_server.toml"
    cfg_file.write_text(
        """
[server.mcp]
read_only = true
auth_token = "mcp-token"
"""
    )
    with patch("hexaqueue_cli.commands.mcp.run_mcp_stdio") as mock_stdio:
        result = runner.invoke(app, ["mcp", "run", "--config", str(cfg_file)])
        assert result.exit_code == 0
        _args, kwargs = mock_stdio.call_args
        cfg = kwargs.get("config")
        assert cfg is not None
        assert cfg.read_only is True
        assert cfg.auth_token == "mcp-token"
        assert cfg.tools.submit_run is False


def test_hq_mcp_run_config_load_error(tmp_path: Path) -> None:
    """Verify corrupted config file exits with error code 1."""
    corrupt_file = tmp_path / "bad_mcp.toml"
    corrupt_file.write_text("invalid [[ toml")
    res = runner.invoke(app, ["mcp", "run", "--config", str(corrupt_file)])
    assert res.exit_code == 1
    assert "Configuration error" in res.output
