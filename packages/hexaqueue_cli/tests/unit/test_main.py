"""Tests for main CLI entrypoint."""

from typer.testing import CliRunner

from hexaqueue_cli.main import app

runner = CliRunner()


def test_main_cli_help() -> None:
    """Verify main entrypoint displays help."""
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "Hexaqueue" in res.stdout
    assert "why" in res.stdout
    assert "explain" in res.stdout
    assert "fairshare" in res.stdout


def test_main_cli_explain_commands_help() -> None:
    """Verify help messages for why, explain, and fairshare commands."""
    res_why = runner.invoke(app, ["why", "--help"])
    assert res_why.exit_code == 0
    assert "why a job is currently waiting" in res_why.stdout

    res_exp = runner.invoke(app, ["explain", "--help"])
    assert res_exp.exit_code == 0
    assert "priority math" in res_exp.stdout

    res_fs = runner.invoke(app, ["fairshare", "--help"])
    assert res_fs.exit_code == 0
    assert "fair-share tree" in res_fs.stdout


def test_main_cli_fairshare_run() -> None:
    """Verify hq fairshare execution in json and table formats."""
    res_json = runner.invoke(app, ["fairshare", "-f", "json"])
    assert res_json.exit_code == 0
    assert '"root"' in res_json.stdout

    res_tbl = runner.invoke(app, ["fairshare"])
    assert res_tbl.exit_code == 0
    assert "Root Hierarchy" in res_tbl.stdout
