"""Tests for CLI commands."""

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from hexaqueue_cli.domain.session import LocalCliSession, set_default_session
from hexaqueue_cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def setup_session() -> None:
    session = LocalCliSession(concurrency=2)
    set_default_session(session)


def test_cli_run_submit_and_watch(tmp_path: Path) -> None:
    """Verify hq run submit with --watch executes to completion."""
    data = {
        "run": {"id": "test-cli-run", "name": "CLI Run"},
        "jobs": [
            {"id": "j1", "name": "step1", "command": "echo 'Hello World'"},
            {"id": "j2", "name": "step2", "command": "echo 'Done'", "depends_on": "j1"},
        ],
    }
    yaml_file = tmp_path / "test_run.yaml"
    with yaml_file.open("w") as f:
        yaml.safe_dump(data, f)

    res = runner.invoke(app, ["run", "submit", str(yaml_file), "--watch"])
    assert res.exit_code == 0
    assert "submitted" in res.stdout
    assert "Run completed" in res.stdout


def test_cli_status_and_logs(tmp_path: Path) -> None:
    """Verify hq status, logs, and cancel commands."""
    data = {
        "run": {"id": "test-status-run"},
        "jobs": [{"id": "job-status-1", "command": "echo 'Status Test Output'"}],
    }
    yaml_file = tmp_path / "status_run.yaml"
    with yaml_file.open("w") as f:
        yaml.safe_dump(data, f)

    submit_res = runner.invoke(app, ["run", "submit", str(yaml_file), "--watch"])
    assert submit_res.exit_code == 0

    status_res = runner.invoke(app, ["status", "test-status-run"])
    assert status_res.exit_code == 0
    assert "test-status-run" in status_res.stdout

    job_status_res = runner.invoke(app, ["status", "job-status-1"])
    assert job_status_res.exit_code == 0
    assert "job-status-1" in job_status_res.stdout

    logs_res = runner.invoke(app, ["logs", "job-status-1"])
    assert logs_res.exit_code == 0
    assert "Status Test Output" in logs_res.stdout


def test_cli_cancel(tmp_path: Path) -> None:
    """Verify hq cancel command."""
    data = {
        "run": {"id": "test-cancel-run"},
        "jobs": [{"id": "cancel-j1", "command": "echo 'Cancel me'"}],
    }
    yaml_file = tmp_path / "cancel_run.yaml"
    with yaml_file.open("w") as f:
        yaml.safe_dump(data, f)

    runner.invoke(app, ["run", "submit", str(yaml_file)])
    cancel_res = runner.invoke(app, ["cancel", "test-cancel-run"])
    assert cancel_res.exit_code == 0
    assert "cancelled" in cancel_res.stdout
