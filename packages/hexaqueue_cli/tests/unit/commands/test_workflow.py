"""Tests for workflow CLI commands."""

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from hexaqueue_cli.commands.workflow import (
    load_workflow_from_target,
    parse_inputs_arg,
)
from hexaqueue_cli.main import app

runner = CliRunner()

WORKFLOW_SCRIPT = """
from hexaflow.domain.models import StageDefinition, StepDefinition, WorkflowDefinition

def step_one():
    return "result_one"

def step_two():
    return "result_two"

workflow = WorkflowDefinition(
    name="sample_pipeline",
    stages=[
        StageDefinition(
            name="stage1",
            steps=[StepDefinition(name="step_one", action=step_one)],
        ),
        StageDefinition(
            name="stage2",
            steps=[StepDefinition(name="step_two", action=step_two)],
        ),
    ],
)
"""

ABORT_WORKFLOW_SCRIPT = """
from hexaflow.domain.models import StageDefinition, StepDefinition, WorkflowDefinition

def comp_action(ctx):
    pass

workflow = WorkflowDefinition(
    name="abort_pipeline",
    stages=[
        StageDefinition(
            name="stage1",
            steps=[StepDefinition(name="step_a", action=lambda: "a", compensation=comp_action)],
        )
    ],
)
"""


@pytest.fixture
def workflow_file(tmp_path: Path) -> Path:
    """Fixture creating a temporary workflow Python file."""
    wf_path = tmp_path / "sample_flow.py"
    wf_path.write_text(WORKFLOW_SCRIPT)
    return wf_path


def test_parse_inputs_arg() -> None:
    """Verify input argument parsing."""
    empty = parse_inputs_arg(None)
    assert empty == {}

    parsed = parse_inputs_arg('{"key": "value", "count": 5}')
    assert parsed == {"key": "value", "count": 5}

    with pytest.raises(typer.BadParameter, match="Invalid JSON"):
        parse_inputs_arg("invalid json string")

    with pytest.raises(typer.BadParameter, match="Input JSON must be an object/dict"):
        parse_inputs_arg("[1, 2, 3]")


def test_load_workflow_from_target(workflow_file: Path, tmp_path: Path) -> None:
    """Verify loading workflow definitions from target strings."""
    # By default filename (looks for 'workflow' attribute)
    wf1 = load_workflow_from_target(str(workflow_file))
    assert wf1.name == "sample_pipeline"

    # With explicit attribute
    wf2 = load_workflow_from_target(f"{workflow_file}:workflow")
    assert wf2.name == "sample_pipeline"

    # Non-existent file
    with pytest.raises(typer.BadParameter, match="does not exist"):
        load_workflow_from_target(str(tmp_path / "missing.py"))

    # Missing attribute
    with pytest.raises(typer.BadParameter, match="does not define attribute"):
        load_workflow_from_target(f"{workflow_file}:non_existent")

    # Invalid object type
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("workflow = 42\n")
    with pytest.raises(
        typer.BadParameter, match="not a Workflow or WorkflowDefinition"
    ):
        load_workflow_from_target(str(bad_file))


def test_workflow_submit_and_status(workflow_file: Path, tmp_path: Path) -> None:
    """Verify hq workflow submit and hq workflow status execution."""
    db_path = tmp_path / "test_state.db"

    # Submit workflow
    submit_res = runner.invoke(
        app,
        [
            "workflow",
            "submit",
            str(workflow_file),
            "--inputs",
            '{"batch_id": 1}',
            "--db",
            str(db_path),
        ],
    )
    assert submit_res.exit_code == 0
    assert "Submitting workflow:" in submit_res.stdout
    assert "sample_pipeline" in submit_res.stdout
    assert "COMPLETED" in submit_res.stdout

    # Extract Run ID from output
    run_id_line = next(
        line for line in submit_res.stdout.splitlines() if "Run ID:" in line
    )
    run_id = run_id_line.split("Run ID:")[1].replace("│", "").strip()

    # Query Status
    status_res = runner.invoke(
        app,
        ["workflow", "status", run_id, "--db", str(db_path)],
    )
    assert status_res.exit_code == 0
    assert run_id in status_res.stdout
    assert "sample_pipeline" in status_res.stdout
    assert "step_one" in status_res.stdout
    assert "step_two" in status_res.stdout


def test_workflow_status_not_found(tmp_path: Path) -> None:
    """Verify error output when workflow run is not found."""
    db_path = tmp_path / "test_state.db"
    status_res = runner.invoke(
        app,
        ["workflow", "status", "non-existent-run", "--db", str(db_path)],
    )
    assert status_res.exit_code == 1
    assert "not found" in status_res.stdout


def test_workflow_resume(workflow_file: Path, tmp_path: Path) -> None:
    """Verify hq workflow resume command."""
    db_path = tmp_path / "test_state.db"

    submit_res = runner.invoke(
        app,
        ["workflow", "submit", str(workflow_file), "--db", str(db_path)],
    )
    assert submit_res.exit_code == 0
    run_id = (
        next(line for line in submit_res.stdout.splitlines() if "Run ID:" in line)
        .split("Run ID:")[1]
        .replace("│", "")
        .strip()
    )

    resume_res = runner.invoke(
        app,
        [
            "workflow",
            "resume",
            run_id,
            str(workflow_file),
            "--db",
            str(db_path),
            "--skip",
            "step_one",
        ],
    )
    assert resume_res.exit_code == 0
    assert "Resuming workflow run:" in resume_res.stdout
    assert run_id in resume_res.stdout


def test_workflow_abort(tmp_path: Path) -> None:
    """Verify hq workflow abort command."""
    db_path = tmp_path / "test_state.db"
    wf_path = tmp_path / "abort_flow.py"
    wf_path.write_text(ABORT_WORKFLOW_SCRIPT)

    submit_res = runner.invoke(
        app,
        ["workflow", "submit", str(wf_path), "--db", str(db_path)],
    )
    assert submit_res.exit_code == 0
    run_id = (
        next(line for line in submit_res.stdout.splitlines() if "Run ID:" in line)
        .split("Run ID:")[1]
        .replace("│", "")
        .strip()
    )

    abort_res = runner.invoke(
        app,
        ["workflow", "abort", run_id, str(wf_path), "--db", str(db_path)],
    )
    assert abort_res.exit_code == 0
    assert "Aborting workflow run:" in abort_res.stdout
    assert "CANCELLED" in abort_res.stdout
