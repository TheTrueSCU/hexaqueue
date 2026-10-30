"""Unit tests for 'hq mcp' CLI commands."""

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
