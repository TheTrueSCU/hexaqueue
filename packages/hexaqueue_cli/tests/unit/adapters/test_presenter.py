"""Unit tests for CliPresenter output formats."""

import json
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import patch

from hexaflow.domain.state import (
    CheckpointRecord,
    StepStatus,
    WorkflowExecutionState,
    WorkflowStatus,
)
from rich.console import Console

from hexaqueue_cli.adapters.presenter import CliPresenter
from hexaqueue_cli.domain.options import OutputFormat
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import (
    RunOutcome,
    RunState,
)
from hexaqueue_server.domain.models import RunStatusReport


def _sample_report() -> RunStatusReport:
    now = datetime.now(UTC)
    return RunStatusReport(
        run_id="run-123",
        state=RunState.DONE,
        outcome=RunOutcome.SUCCEEDED,
        total_jobs=4,
        completed_jobs=4,
        failed_jobs=0,
        running_jobs=0,
        pending_jobs=0,
        created_at=now,
        updated_at=now,
    )


def _sample_job() -> JobSpec:
    return JobSpec(
        id="job-456",
        run_id="run-123",
        name="compute-step",
        command="python task.py",
    )


def _sample_workflow_state() -> tuple[WorkflowExecutionState, list[CheckpointRecord]]:
    now = datetime.now(UTC)
    state = WorkflowExecutionState(
        run_id="wf-run-789",
        workflow_name="etl-pipeline",
        status=WorkflowStatus.COMPLETED,
        current_stage="finalize",
        started_at=now,
        finished_at=now,
    )
    checkpoints = [
        CheckpointRecord(
            run_id="wf-run-789",
            stage_name="ingest",
            step_name="fetch-data",
            status=StepStatus.COMPLETED,
            attempt_number=1,
            input_payload={"source": "api"},
            output_payload={"records": 100},
            started_at=now,
            completed_at=now,
            duration_seconds=1.234,
        )
    ]
    return state, checkpoints


def test_render_run_status_json() -> None:
    """Verify run status renders clean JSON."""
    buf = StringIO()
    presenter = CliPresenter(console=Console(file=buf))
    report = _sample_report()

    with patch("sys.stdout", buf):
        presenter.render_run_status(report, OutputFormat.JSON)

    out = buf.getvalue()
    data = json.loads(out)
    assert data["run_id"] == "run-123"
    assert data["state"] == "DONE"
    assert data["total_jobs"] == 4


def test_render_run_status_markdown() -> None:
    """Verify run status renders markdown table."""
    buf = StringIO()
    presenter = CliPresenter(console=Console(file=buf))
    report = _sample_report()

    with patch("sys.stdout", buf):
        presenter.render_run_status(report, OutputFormat.MARKDOWN)

    out = buf.getvalue()
    assert "| Run ID | `run-123` |" in out
    assert "| Total Jobs | 4 |" in out


def test_render_run_status_plain() -> None:
    """Verify run status renders plain tab-separated lines."""
    buf = StringIO()
    presenter = CliPresenter(console=Console(file=buf))
    report = _sample_report()

    with patch("sys.stdout", buf):
        presenter.render_run_status(report, OutputFormat.PLAIN)

    out = buf.getvalue()
    assert "run_id\trun-123" in out
    assert "total_jobs\t4" in out


def test_render_run_status_table() -> None:
    """Verify run status renders interactive Rich table."""
    buf = StringIO()
    console = Console(file=buf, no_color=True)
    presenter = CliPresenter(console=console)
    report = _sample_report()

    presenter.render_run_status(report, OutputFormat.TABLE)
    out = buf.getvalue()
    assert "run-123" in out
    assert "DONE" in out


def test_render_job_formats() -> None:
    """Verify single job rendering across json, markdown, plain, table."""
    job = _sample_job()

    # JSON
    buf_json = StringIO()
    presenter_json = CliPresenter(console=Console(file=buf_json))
    with patch("sys.stdout", buf_json):
        presenter_json.render_job(job, "json")
    parsed = json.loads(buf_json.getvalue())
    assert parsed["id"] == "job-456"
    assert parsed["command"] == "python task.py"

    # Markdown
    buf_md = StringIO()
    presenter_md = CliPresenter(console=Console(file=buf_md))
    with patch("sys.stdout", buf_md):
        presenter_md.render_job(job, "markdown")
    out_md = buf_md.getvalue()
    assert "| Job ID | `job-456` |" in out_md

    # Plain
    buf_plain = StringIO()
    presenter_plain = CliPresenter(console=Console(file=buf_plain))
    with patch("sys.stdout", buf_plain):
        presenter_plain.render_job(job, "plain")
    out_plain = buf_plain.getvalue()
    assert "id\tjob-456" in out_plain

    # Table
    buf_table = StringIO()
    console = Console(file=buf_table, no_color=True)
    presenter_table = CliPresenter(console=console)
    presenter_table.render_job(job, "table")
    out_table = buf_table.getvalue()
    assert "job-456" in out_table


def test_render_workflow_state_formats() -> None:
    """Verify workflow state rendering across json, markdown, plain, table."""
    state, checkpoints = _sample_workflow_state()

    # JSON
    buf_json = StringIO()
    presenter_json = CliPresenter(console=Console(file=buf_json))
    with patch("sys.stdout", buf_json):
        presenter_json.render_workflow_state(state, checkpoints, "json")
    parsed = json.loads(buf_json.getvalue())
    assert parsed["run_id"] == "wf-run-789"
    assert parsed["workflow_name"] == "etl-pipeline"
    assert len(parsed["checkpoints"]) == 1

    # Markdown
    buf_md = StringIO()
    presenter_md = CliPresenter(console=Console(file=buf_md))
    with patch("sys.stdout", buf_md):
        presenter_md.render_workflow_state(state, checkpoints, "markdown")
    out_md = buf_md.getvalue()
    assert "### Workflow Run: etl-pipeline (`wf-run-789`)" in out_md
    assert "| ingest | fetch-data | COMPLETED |" in out_md

    # Plain
    buf_plain = StringIO()
    presenter_plain = CliPresenter(console=Console(file=buf_plain))
    with patch("sys.stdout", buf_plain):
        presenter_plain.render_workflow_state(state, checkpoints, "plain")
    out_plain = buf_plain.getvalue()
    assert "run_id\twf-run-789" in out_plain
    assert "ingest\tfetch-data\tCOMPLETED" in out_plain

    # Table
    buf_table = StringIO()
    console = Console(file=buf_table, no_color=True)
    presenter_table = CliPresenter(console=console)
    presenter_table.render_workflow_state(state, checkpoints, "table")
    out_table = buf_table.getvalue()
    assert "etl-pipeline" in out_table
    assert "fetch-data" in out_table
