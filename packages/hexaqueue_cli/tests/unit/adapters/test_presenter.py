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
from hexaqueue_core.domain.freetier import CspProvider, FreeTierBurnReport
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


def _sample_burn_report(is_throttled: bool = False) -> FreeTierBurnReport:
    return FreeTierBurnReport(
        active_jobs_count=2,
        allocated_cpus=2,
        allocated_ram_mb=2048,
        allocated_storage_mb=1024,
        cpu_ceiling=2,
        cpu_utilization_pct=100.0,
        is_throttled=is_throttled,
        profile_name="Local Container / Developer Sandbox",
        provider=CspProvider.LOCAL,
        ram_ceiling_mb=2048,
        ram_utilization_pct=100.0,
        storage_ceiling_mb=5120,
        storage_utilization_pct=20.0,
    )


def test_render_run_status_free_tier_table() -> None:
    """Verify run status renders [FREE TIER ACTIVE] badge and burn meter table."""
    buf = StringIO()
    presenter = CliPresenter(console=Console(file=buf, no_color=True, width=120))
    now = datetime.now(UTC)
    burn = _sample_burn_report(is_throttled=True)
    report = RunStatusReport(
        burn_report=burn,
        completed_jobs=2,
        created_at=now,
        failed_jobs=0,
        free_tier_active=True,
        outcome=RunOutcome.SUCCEEDED,
        pending_jobs=0,
        run_id="run-free-tier",
        running_jobs=0,
        state=RunState.DONE,
        total_jobs=2,
    )

    presenter.render_run_status(report, OutputFormat.TABLE)
    out = buf.getvalue()
    assert "FREE TIER ACTIVE" in out
    assert "Free-Tier Quota Burn Meter" in out
    assert "THROTTLED" in out
    assert "Developer" in out
    assert "Sandbox" in out
    assert "Local Container" in out


def test_render_run_status_free_tier_json() -> None:
    """Verify run status in JSON includes free_tier_active and burn_report."""
    buf = StringIO()
    presenter = CliPresenter(console=Console(file=buf))
    now = datetime.now(UTC)
    burn = _sample_burn_report(is_throttled=False)
    report = RunStatusReport(
        burn_report=burn,
        completed_jobs=1,
        created_at=now,
        failed_jobs=0,
        free_tier_active=True,
        outcome=None,
        pending_jobs=1,
        run_id="run-ft-json",
        running_jobs=1,
        state=RunState.RUNNING,
        total_jobs=2,
    )

    with patch("sys.stdout", buf):
        presenter.render_run_status(report, OutputFormat.JSON)

    data = json.loads(buf.getvalue())
    assert data["free_tier_active"] is True
    assert data["burn_report"] is not None
    assert data["burn_report"]["profile_name"] == "Local Container / Developer Sandbox"
    assert data["burn_report"]["cpu_utilization_pct"] == 100.0


def test_render_run_status_free_tier_markdown() -> None:
    """Verify run status in Markdown includes free-tier header and quota burn section."""
    buf = StringIO()
    presenter = CliPresenter(console=Console(file=buf))
    now = datetime.now(UTC)
    burn = _sample_burn_report(is_throttled=False)
    report = RunStatusReport(
        burn_report=burn,
        completed_jobs=1,
        created_at=now,
        failed_jobs=0,
        free_tier_active=True,
        outcome=None,
        pending_jobs=0,
        run_id="run-ft-md",
        running_jobs=1,
        state=RunState.RUNNING,
        total_jobs=1,
    )

    with patch("sys.stdout", buf):
        presenter.render_run_status(report, OutputFormat.MARKDOWN)

    out = buf.getvalue()
    assert "[FREE TIER ACTIVE]" in out
    assert "Free-Tier Quota Burn" in out
    assert "2 cores" in out


def test_render_cluster_stats_all_formats() -> None:
    """Verify render_cluster_stats across JSON, Markdown, Plain, and Table formats."""
    from hexaqueue_cli.domain.models import ClusterStatsReport

    stats = ClusterStatsReport(
        total_runs=2,
        total_jobs=5,
        running_jobs=1,
        pending_jobs=2,
        blocked_jobs=1,
        completed_jobs=1,
        failed_jobs=0,
        active_workers=1,
    )

    # JSON format
    buf_json = StringIO()
    p_json = CliPresenter(console=Console(file=buf_json))
    p_json.render_cluster_stats(stats, OutputFormat.JSON)
    json_out = buf_json.getvalue()
    data = json.loads(json_out)
    res_runs = data["total_runs"]
    assert res_runs == 2

    # Markdown format
    buf_md = StringIO()
    p_md = CliPresenter(console=Console(file=buf_md))
    p_md.render_cluster_stats(stats, OutputFormat.MARKDOWN)
    md_out = buf_md.getvalue()
    assert "Cluster State Summary" in md_out
    assert "Total Runs" in md_out

    # Plain format
    buf_plain = StringIO()
    p_plain = CliPresenter(console=Console(file=buf_plain))
    p_plain.render_cluster_stats(stats, OutputFormat.PLAIN)
    plain_out = buf_plain.getvalue()
    assert "RUNS=2" in plain_out
    assert "JOBS=5" in plain_out

    # Table format
    buf_tbl = StringIO()
    p_tbl = CliPresenter(console=Console(file=buf_tbl))
    p_tbl.render_cluster_stats(stats, OutputFormat.TABLE)
    tbl_out = buf_tbl.getvalue()
    assert "Hexaqueue Cluster Status" in tbl_out
    assert "Running Jobs" in tbl_out


def test_render_nodes_table_all_formats() -> None:
    """Verify render_nodes_table across JSON, Markdown, Plain, and Table formats."""
    from hexaqueue_worker.domain.telemetry import GpuTelemetry, NodeTelemetryPulse

    gpu = GpuTelemetry(
        index=0,
        model="NVIDIA A100-SXM4-80GB",
        utilization_pct=45.0,
        vram_used_mb=32768,
        vram_total_mb=81920,
        temperature_c=55.0,
    )
    node = NodeTelemetryPulse(
        worker_id="node-test-1",
        cpu_utilization_pct=25.0,
        load_average=(1.5, 1.2, 0.9),
        memory_used_mb=16384,
        memory_total_mb=65536,
        scratch_used_mb=1024,
        scratch_total_mb=10240,
        active_jobs=2,
        gpu_metrics=[gpu],
    )

    # JSON format
    buf_json = StringIO()
    p_json = CliPresenter(console=Console(file=buf_json))
    p_json.render_nodes_table([node], OutputFormat.JSON)
    json_out = buf_json.getvalue()
    data = json.loads(json_out)
    assert len(data) == 1
    res_worker_id = data[0]["worker_id"]
    assert res_worker_id == "node-test-1"

    # Markdown format
    buf_md = StringIO()
    p_md = CliPresenter(console=Console(file=buf_md))
    p_md.render_nodes_table([node], OutputFormat.MARKDOWN)
    md_out = buf_md.getvalue()
    assert "node-test-1" in md_out
    assert "Node ID" in md_out

    # Plain format
    buf_plain = StringIO()
    p_plain = CliPresenter(console=Console(file=buf_plain))
    p_plain.render_nodes_table([node], OutputFormat.PLAIN)
    plain_out = buf_plain.getvalue()
    assert "NODE=node-test-1" in plain_out

    # Table format
    buf_tbl = StringIO()
    p_tbl = CliPresenter(console=Console(file=buf_tbl, width=200))
    p_tbl.render_nodes_table([node], OutputFormat.TABLE)
    tbl_out = buf_tbl.getvalue()
    assert "Compute Nodes Telemetry" in tbl_out
    assert "node-test-1" in tbl_out


def test_top_dashboard_rendering() -> None:
    """Verify build_top_dashboard and render_top_dashboard."""
    from hexaqueue_cli.domain.models import ClusterStatsReport
    from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse

    stats = ClusterStatsReport(total_runs=1, total_jobs=2, running_jobs=1)
    node = NodeTelemetryPulse(
        worker_id="node-1",
        cpu_utilization_pct=15.0,
        load_average=(0.5, 0.4, 0.3),
        memory_used_mb=4096,
        memory_total_mb=16384,
        scratch_used_mb=500,
        scratch_total_mb=5000,
        active_jobs=1,
    )
    job = JobSpec(
        id="job-top-1",
        run_id="run-1",
        name="training",
        command="python train.py",
    )

    buf = StringIO()
    presenter = CliPresenter(console=Console(file=buf))
    group = presenter.build_top_dashboard(stats, [node], [job])
    assert group is not None

    presenter.render_top_dashboard(stats, [node], [job])
    out = buf.getvalue()
    assert "Hexaqueue Cluster Summary" in out
    assert "Worker Nodes" in out
    assert "Active & Queued Jobs" in out
    assert "job-top-1" in out
