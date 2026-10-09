"""Unit tests for CQRS command and query domain models."""

from hexaqueue_core.domain.collateral import CollateralKind, CollateralTier
from hexaqueue_core.domain.cqrs import (
    CancelJobCommand,
    CancelRunCommand,
    CreateBastionSessionCommand,
    CreatePtySessionCommand,
    ExplainJobQuery,
    GetFairShareTreeQuery,
    GetJobLogDownloadUrlQuery,
    GetJobQuery,
    GetLogsQuery,
    GetNodesQuery,
    GetQueueStatsQuery,
    GetRunStatusQuery,
    HoldJobCommand,
    ListJobsQuery,
    NotifyLogUploadCompleteCommand,
    PresignedDownloadUrl,
    PresignedUploadToken,
    RegisterCollateralCommand,
    ReleaseJobCommand,
    RequestLogUploadUrlCommand,
    SettleBudgetCommand,
    StreamLogsQuery,
    SubmitRunCommand,
    SubmitSuiteCommand,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.retention import LogRetentionPolicy, LogRetentionTier
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


def test_presigned_log_cqrs_models() -> None:
    """Test CQRS commands and queries for presigned log upload and streaming."""
    policy = LogRetentionPolicy.for_outcome(TerminalOutcome.COMPLETED)
    cmd_upload = RequestLogUploadUrlCommand(
        job_id="job-42",
        outcome=TerminalOutcome.COMPLETED,
        size_bytes=1024,
        expires_in_seconds=600,
    )
    job_id = cmd_upload.job_id
    assert job_id == "job-42"
    assert cmd_upload.outcome == TerminalOutcome.COMPLETED
    assert cmd_upload.size_bytes == 1024
    assert cmd_upload.expires_in_seconds == 600

    token = PresignedUploadToken(
        job_id="job-42",
        upload_url="https://s3.example.com/upload",
        storage_key="logs/job-42/stdout.log",
        retention_policy=policy,
        expires_in_seconds=600,
    )
    assert token.upload_url == "https://s3.example.com/upload"
    assert token.retention_policy.tier == LogRetentionTier.SHORT_PASS

    cmd_complete = NotifyLogUploadCompleteCommand(
        job_id="job-42",
        storage_key="logs/job-42/stdout.log",
        sha256_checksum="a" * 64,
        size_bytes=2048,
    )
    assert cmd_complete.storage_key == "logs/job-42/stdout.log"
    assert cmd_complete.size_bytes == 2048

    query_dl = GetJobLogDownloadUrlQuery(job_id="job-42", expires_in_seconds=1200)
    assert query_dl.job_id == "job-42"
    assert query_dl.expires_in_seconds == 1200

    dl_url = PresignedDownloadUrl(
        job_id="job-42",
        download_url="https://s3.example.com/download",
        storage_key="logs/job-42/stdout.log",
        expires_in_seconds=1200,
    )
    assert dl_url.download_url == "https://s3.example.com/download"
    assert dl_url.expires_in_seconds == 1200


def test_node_and_dlq_cqrs_models() -> None:
    """Test CQRS commands, queries, and reports for compute nodes and DLQ."""
    from hexaqueue_core.domain.cqrs import (
        DeadLetterQueueReport,
        GetDeadLetterQueueQuery,
        HeartbeatNodeCommand,
        ListComputeNodesQuery,
        NodesReport,
        RegisterNodeCommand,
    )
    from hexaqueue_core.domain.node import ComputeNodeProfile
    from hexaqueue_core.domain.retry import DeadLetterRecord

    profile = ComputeNodeProfile(node_id="worker-node-1")
    reg_cmd = RegisterNodeCommand(profile=profile)
    reg_id = reg_cmd.profile.node_id
    assert reg_id == "worker-node-1"

    list_nodes_qry = ListComputeNodesQuery()
    qry_user = list_nodes_qry.user_id
    assert qry_user == "default"

    hb_cmd = HeartbeatNodeCommand(
        worker_id="worker-node-1",
        active_job_ids=["job-1"],
        cached_collateral_hashes=["hash-abc"],
    )
    hb_id = hb_cmd.worker_id
    assert hb_id == "worker-node-1"
    assert "job-1" in hb_cmd.active_job_ids

    nodes_rep = NodesReport(nodes=[profile], total_nodes=1)
    tot_nodes = nodes_rep.total_nodes
    assert tot_nodes == 1

    dlq_query = GetDeadLetterQueueQuery(limit=25)
    q_limit = dlq_query.limit
    assert q_limit == 25

    record = DeadLetterRecord(
        job_id="job-err",
        run_id="run-err",
        failure_reason="OOMKilled",
        retry_count=3,
    )
    dlq_rep = DeadLetterQueueReport(records=[record], total_count=1)
    dlq_count = dlq_rep.total_count
    assert dlq_count == 1
