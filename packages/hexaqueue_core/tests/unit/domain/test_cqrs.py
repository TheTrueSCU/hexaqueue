"""Unit tests for CQRS command and query domain models."""

from hexaqueue_core.domain.collateral import CollateralKind, CollateralTier
from hexaqueue_core.domain.cqrs import (
    CancelJobCommand,
    CancelRunCommand,
    CreateBastionSessionCommand,
    CreatePtySessionCommand,
    ExplainJobQuery,
    GetFairShareTreeQuery,
    GetJobQuery,
    GetLogsQuery,
    GetNodesQuery,
    GetQueueStatsQuery,
    GetRunStatusQuery,
    HoldJobCommand,
    ListJobsQuery,
    RegisterCollateralCommand,
    ReleaseJobCommand,
    SettleBudgetCommand,
    StreamLogsQuery,
    SubmitRunCommand,
    SubmitSuiteCommand,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.domain.suite import SuiteSpec, TaskSpec


def test_submit_run_command() -> None:
    """Test SubmitRunCommand creation and serialization."""
    run_spec = RunSpec(id="run-1", name="Test Run")
    job = JobSpec(
        id="job-1",
        run_id="run-1",
        name="task-1",
        command="echo 1",
        resources=ResourceRequirements(cpus=1, ram_mb=1024),
    )
    cmd = SubmitRunCommand(
        run_spec=run_spec,
        jobs=[job],
        dependencies={"job-1": []},
        user_id="alice",
        elevate=False,
    )
    assert cmd.run_spec.id == "run-1"
    assert len(cmd.jobs) == 1
    assert cmd.user_id == "alice"
    assert cmd.elevate is False


def test_submit_suite_command() -> None:
    """Test SubmitSuiteCommand creation and default elevation."""
    suite = SuiteSpec(
        id="suite-1",
        name="Inference Suite",
        tasks=[TaskSpec(id="task-1", command="echo hello")],
    )
    cmd = SubmitSuiteCommand(suite_spec=suite, user_id="bob", elevate=True)
    assert cmd.suite_spec.id == "suite-1"
    assert cmd.user_id == "bob"
    assert cmd.elevate is True


def test_lifecycle_commands() -> None:
    """Test job and run lifecycle commands."""
    c_run = CancelRunCommand(run_id="run-99", user_id="carol", elevate=False)
    assert c_run.run_id == "run-99"

    h_job = HoldJobCommand(job_id="job-42", user_id="dave", elevate=True)
    assert h_job.job_id == "job-42"
    assert h_job.elevate is True

    r_job = ReleaseJobCommand(job_id="job-42", user_id="dave", elevate=True)
    assert r_job.job_id == "job-42"

    k_job = CancelJobCommand(job_id="job-42", user_id="dave", elevate=False)
    assert k_job.job_id == "job-42"


def test_collateral_and_terminal_commands() -> None:
    """Test RegisterCollateral, CreatePtySession, and SettleBudget commands."""
    col_cmd = RegisterCollateralCommand(
        name="weights.bin",
        checksum_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        size_bytes=1024,
        tier=CollateralTier.TEMPORARY,
        kind=CollateralKind.DATASET,
    )
    assert col_cmd.name == "weights.bin"
    assert col_cmd.kind == CollateralKind.DATASET

    pty_cmd = CreatePtySessionCommand(
        job_id="job-10",
        session_id="pty-sess-1",
        command=["/bin/sh"],
        user_id="admin",
        elevate=True,
    )
    assert pty_cmd.job_id == "job-10"
    assert pty_cmd.rows == 24
    assert pty_cmd.cols == 80

    bastion_cmd = CreateBastionSessionCommand(
        node_id="node-gpu-01",
        session_id="ssh-sess-1",
        user_id="operator",
        elevate=True,
    )
    assert bastion_cmd.node_id == "node-gpu-01"

    budget_cmd = SettleBudgetCommand(project_id="proj-ai", amount_cents=5000)
    assert budget_cmd.amount_cents == 5000


def test_query_models() -> None:
    """Test all Query domain models."""
    q_run = GetRunStatusQuery(run_id="run-1")
    assert q_run.run_id == "run-1"

    q_job = GetJobQuery(job_id="job-1")
    assert q_job.job_id == "job-1"

    q_list = ListJobsQuery(run_id="run-1")
    assert q_list.run_id == "run-1"

    q_exp = ExplainJobQuery(job_id="job-1", requesting_user="alice", is_admin=True)
    assert q_exp.is_admin is True

    q_tree = GetFairShareTreeQuery(requesting_user="bob", is_admin=False)
    assert q_tree.requesting_user == "bob"

    q_stats = GetQueueStatsQuery()
    assert q_stats.user_id == "default"

    q_nodes = GetNodesQuery()
    assert q_nodes.elevate is False

    q_logs = GetLogsQuery(job_id="job-1", tail=100)
    assert q_logs.tail == 100

    q_stream = StreamLogsQuery(job_id="job-1", follow=True)
    assert q_stream.follow is True
