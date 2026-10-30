"""Unit tests for 'hq server' CLI commands."""

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
