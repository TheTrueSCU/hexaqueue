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


def test_cli_run_submit_with_notifications(tmp_path: Path) -> None:
    """Verify hq run submit accepts --notify and --notify-on options."""
    data = {
        "run": {"id": "test-notif-run", "name": "Notif Run"},
        "jobs": [
            {"id": "j_notif", "name": "step_notif", "command": "echo 'Notif Test'"},
        ],
    }
    yaml_file = tmp_path / "notif_run.yaml"
    with yaml_file.open("w") as f:
        yaml.safe_dump(data, f)

    res = runner.invoke(
        app,
        [
            "run",
            "submit",
            str(yaml_file),
            "--notify",
            "slack://channel-a,discord://channel-b",
            "--notify-on",
            "COMPLETED,FAILED",
            "--watch",
        ],
    )
    assert res.exit_code == 0
    assert "submitted" in res.stdout
    assert "Run completed" in res.stdout


def test_cli_run_submit_free_tier(tmp_path: Path) -> None:
    """Verify hq run submit with --free-tier clamps non-compliant jobs."""
    data = {
        "run": {"id": "test-free-tier-run", "name": "Free Tier Run"},
        "jobs": [
            {
                "id": "gpu-job",
                "name": "gpu-task",
                "command": "torchrun",
                "resources": {"gpus": 1},
            },
        ],
    }
    yaml_file = tmp_path / "free_tier_run.yaml"
    with yaml_file.open("w") as f:
        yaml.safe_dump(data, f)

    res = runner.invoke(
        app,
        ["run", "submit", str(yaml_file), "--free-tier"],
    )
    assert res.exit_code == 0
    assert "submitted" in res.stdout


def test_cli_permission_elevation_for_cross_user_mutations(tmp_path: Path) -> None:
    """Verify that mutating another user's job requires explicit --admin elevation."""
    data = {
        "run": {"id": "run-owned", "tags": ["owner:alice"]},
        "jobs": [
            {
                "id": "job-alice-1",
                "command": "sleep 10",
                "tags": ["owner:alice"],
            }
        ],
    }
    yaml_file = tmp_path / "owned_run.yaml"
    with yaml_file.open("w") as f:
        yaml.safe_dump(data, f)

    submit_res = runner.invoke(app, ["run", "submit", str(yaml_file)])
    assert submit_res.exit_code == 0

    # 1. Bob attempts to hold Alice's job without --admin -> denied
    bob_hold_denied = runner.invoke(app, ["hold", "job-alice-1", "--user", "bob"])
    assert bob_hold_denied.exit_code == 1
    assert "Permission denied" in bob_hold_denied.stdout
    assert "--admin" in bob_hold_denied.stdout

    # 2. Bob holds Alice's job with positive --admin elevation -> succeeds
    bob_hold_elevated = runner.invoke(
        app, ["hold", "job-alice-1", "--user", "bob", "--admin"]
    )
    assert bob_hold_elevated.exit_code == 0
    assert "placed on administrative hold" in bob_hold_elevated.stdout

    # 3. Bob releases Alice's job with positive --admin elevation -> succeeds
    bob_rel_elevated = runner.invoke(
        app, ["release", "job-alice-1", "--user", "bob", "--admin"]
    )
    assert bob_rel_elevated.exit_code == 0
    assert "released from hold" in bob_rel_elevated.stdout

    # 4. Bob cancels Alice's job without --admin -> denied
    bob_cancel_denied = runner.invoke(app, ["cancel", "job-alice-1", "--user", "bob"])
    assert bob_cancel_denied.exit_code == 1
    assert "Permission denied" in bob_cancel_denied.stdout

    # 5. Bob cancels Alice's job with --admin -> succeeds
    bob_cancel_elevated = runner.invoke(
        app, ["cancel", "job-alice-1", "--user", "bob", "--admin"]
    )
    assert bob_cancel_elevated.exit_code == 0
    assert "cancelled" in bob_cancel_elevated.stdout
