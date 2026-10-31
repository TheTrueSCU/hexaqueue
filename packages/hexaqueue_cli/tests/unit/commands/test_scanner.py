"""Unit tests for hq scanner CLI commands."""

from pathlib import Path

from typer.testing import CliRunner

from hexaqueue_cli.main import app

runner = CliRunner()


def test_cli_scanner_help() -> None:
    """Verify hq scanner --help displays subcommands."""
    res = runner.invoke(app, ["scanner", "--help"])
    exit_code = res.exit_code
    assert exit_code == 0
    stdout = res.stdout
    assert "file" in stdout
    assert "daemon" in stdout
    assert "ping" in stdout


def test_cli_scanner_file_clean(tmp_path: Path) -> None:
    """Verify scanning a clean file returns success exit code 0."""
    target_file = tmp_path / "clean_test_artifact.bin"
    target_file.write_bytes(b"safe and non-malicious content")

    res = runner.invoke(app, ["scanner", "file", str(target_file)])
    exit_code = res.exit_code
    assert exit_code == 0
    stdout = res.stdout
    assert "Artifact is verified clean" in stdout


def test_cli_scanner_ping() -> None:
    """Verify hq scanner ping executes without crashing."""
    res = runner.invoke(
        app,
        ["scanner", "ping", "--clamav-socket", "/nonexistent/path/clamd.ctl"],
    )
    exit_code = res.exit_code
    assert exit_code == 0
    stdout = res.stdout
    assert "unreachable" in stdout or "healthy" in stdout
