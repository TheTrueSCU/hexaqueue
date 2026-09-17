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


def test_render_why_summary_and_explain() -> None:
    """Verify render_why_summary and render_explain_report formats."""
    from hexaqueue_core.domain.explainability import (
        FairShareNodeReport,
        FairShareTreeReport,
        PendingReason,
        PendingReasonCode,
        PriorityBreakdown,
        SchedulingDecisionReport,
    )
    from hexaqueue_core.domain.lifecycle import JobState

    bd = PriorityBreakdown(
        base_score=100.0,
        age_score=50.0,
        fairshare_score=250.0,
        preemption_bonus=0.0,
        total_priority=400.0,
        age_seconds=120.0,
        fairshare_factor=0.75,
        target_share=0.5,
        actual_usage=500.0,
    )
    report = SchedulingDecisionReport(
        job_id="job-exp-1",
        user="test-user",
        state=JobState.PENDING,
        queue_position=1,
        queue_total=3,
        priority_breakdown=bd,
        pending_reasons=[
            PendingReason(
                code=PendingReasonCode.READY,
                message="Job is at top of queue",
            )
        ],
        required_slots=2,
        available_slots=4,
        total_slots=8,
        summary="Job 'job-exp-1' is ready for immediate dispatch.",
    )

    # render_why_summary
    buf_why = StringIO()
    p_why = CliPresenter(console=Console(file=buf_why, no_color=True))
    p_why.render_why_summary(report)
    out_why = buf_why.getvalue()
    assert "ready for immediate dispatch" in out_why

    # render_explain_report - table
    buf_tbl = StringIO()
    p_tbl = CliPresenter(console=Console(file=buf_tbl, no_color=True))
    p_tbl.render_explain_report(report, "table")
    out_tbl = buf_tbl.getvalue()
    assert "job-exp-1" in out_tbl
    assert "400.00" in out_tbl

    # render_explain_report - json
    buf_json = StringIO()
    p_json = CliPresenter(console=Console(file=buf_json))
    p_json.render_explain_report(report, "json")
    parsed = json.loads(buf_json.getvalue())
    assert parsed["job_id"] == "job-exp-1"
    assert parsed["queue_position"] == 1

    # render_explain_report - plain
    buf_plain = StringIO()
    p_plain = CliPresenter(console=Console(file=buf_plain))
    p_plain.render_explain_report(report, "plain")
    out_plain = buf_plain.getvalue()
    assert "Job ID: job-exp-1" in out_plain

    # render_fairshare_tree
    tree_report = FairShareTreeReport(
        root=FairShareNodeReport(
            id="root",
            shares=1.0,
            target_share=1.0,
            raw_usage=100.0,
            decayed_usage=100.0,
            fairshare_factor=1.0,
            children=[
                FairShareNodeReport(
                    id="team-a",
                    parent_id="root",
                    shares=1.0,
                    target_share=1.0,
                    raw_usage=100.0,
                    decayed_usage=100.0,
                    fairshare_factor=0.5,
                    children=[],
                )
            ],
        ),
        half_life_seconds=86400.0,
        total_decayed_usage=100.0,
    )
    buf_tree = StringIO()
    p_tree = CliPresenter(console=Console(file=buf_tree, no_color=True))
    p_tree.render_fairshare_tree(tree_report, "table")
    out_tree = buf_tree.getvalue()
    assert "team-a" in out_tree

    buf_tree_json = StringIO()
    p_tree_json = CliPresenter(console=Console(file=buf_tree_json))
    p_tree_json.render_fairshare_tree(tree_report, "json")
    parsed_tree = json.loads(buf_tree_json.getvalue())
    assert parsed_tree["root"]["id"] == "root"
