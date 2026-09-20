"""Unit tests for hq suite CLI commands."""

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from hexaqueue_cli.domain.session import LocalCliSession, set_default_session
from hexaqueue_cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def setup_session() -> None:
    """Hermetic session fixture."""
    session = LocalCliSession(concurrency=2)
    set_default_session(session)


def test_cli_suite_run_command(tmp_path: Path) -> None:
    """Verify hq suite run parses and executes suite workloads."""
    suite_data = {
        "id": "suite-test-1",
        "name": "Integration Suite",
        "tasks": [
            {
                "id": "task-1",
                "command": "echo 'running task 1'",
            },
            {
                "id": "task-2",
                "command": "echo 'running task 2'",
                "depends_on": ["task-1"],
            },
        ],
    }
    yaml_file = tmp_path / "test_suite.yaml"
    with yaml_file.open("w", encoding="utf-8") as f:
        yaml.safe_dump(suite_data, f)

    res = runner.invoke(app, ["suite", "run", str(yaml_file), "--admin"])
    assert res.exit_code == 0
    assert "Suite workload submitted successfully" in res.stdout
    assert "suite-test-1" in res.stdout


def test_cli_top_level_submit_suite_forwarding(tmp_path: Path) -> None:
    """Verify top-level hq submit detects suite specs and forwards appropriately."""
    suite_data = {
        "id": "suite-auto-forward",
        "name": "Forwarding Suite",
        "tasks": [
            {
                "id": "leaf-task",
                "command": "echo forward",
            }
        ],
    }
    yaml_file = tmp_path / "forward_suite.yaml"
    with yaml_file.open("w", encoding="utf-8") as f:
        yaml.safe_dump(suite_data, f)

    res = runner.invoke(app, ["submit", str(yaml_file)])
    assert res.exit_code == 0
    assert "Suite workload submitted successfully" in res.stdout
