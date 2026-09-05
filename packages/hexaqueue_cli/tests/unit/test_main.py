"""Tests for main CLI entrypoint."""

from typer.testing import CliRunner

from hexaqueue_cli.main import app

runner = CliRunner()


def test_main_cli_help() -> None:
    """Verify main entrypoint displays help."""
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "Hexaqueue" in res.stdout
