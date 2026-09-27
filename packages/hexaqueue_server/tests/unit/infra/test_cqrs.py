"""Unit tests for Hexaqueue Server CQRS pipeline and permission elevation."""

from collections.abc import Generator
from typing import Any

import pytest
from hexastack_cqrs.infra.pipeline import ExecutionPipeline

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.cqrs import (
    CancelJobCommand,
    CreateBastionSessionCommand,
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
    SubmitRunCommand,
    SubmitSuiteCommand,
)
from hexaqueue_core.domain.exceptions import PermissionDeniedError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.domain.suite import SuiteSpec, TaskSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


@pytest.fixture
def hermetic_cqrs_pipeline() -> Generator[
    tuple[LocalSchedulerControllerAdapter, ExecutionPipeline]
]:
    """Hermetic fixture providing a clean controller and execution pipeline."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    log_store: dict[str, list[LogChunk]] = {
        "job-log-1": [
            LogChunk(
                job_id="job-log-1",
                stream="stdout",
                content="Starting worker process\n",
                offset=0,
            ),
            LogChunk(
                job_id="job-log-1",
                stream="stdout",
                content="Execution complete\n",
                offset=1,
            ),
        ]
    }
    pipeline = create_hexaqueue_execution_pipeline(
        controller=controller, log_store=log_store
    )
    yield controller, pipeline


def test_submit_run_and_status(hermetic_cqrs_pipeline: tuple[Any, Any]) -> None:
    """Verify submitting a run via CQRS and querying its status."""
    _, pipeline = hermetic_cqrs_pipeline
    run_spec = RunSpec(id="run-100", name="Test Pipeline")
    job = JobSpec(
        id="job-101",
        run_id="run-100",
        name="task-a",
        command="echo task-a",
        resources=ResourceRequirements(cpus=1, ram_mb=1024),
        tags=["owner:alice"],
    )
    cmd = SubmitRunCommand(
        run_spec=run_spec,
        jobs=[job],
        user_id="alice",
        elevate=False,
    )
    report = pipeline.execute(cmd)
    assert report.run_id == "run-100"
    assert report.total_jobs == 1

    qry = GetRunStatusQuery(run_id="run-100", user_id="alice")
    status_report = pipeline.execute(qry)
    assert status_report.run_id == "run-100"
    assert status_report.total_jobs == 1


def test_submit_suite_command(hermetic_cqrs_pipeline: tuple[Any, Any]) -> None:
    """Verify submitting a hierarchical suite workload via CQRS."""
    _, pipeline = hermetic_cqrs_pipeline
    suite = SuiteSpec(
        id="suite-alpha",
        name="Alpha Suite",
        tasks=[TaskSpec(id="task-1", command="echo matrix")],
    )
    cmd = SubmitSuiteCommand(suite_spec=suite, user_id="bob", elevate=False)
    report = pipeline.execute(cmd)
    assert report.run_id == "suite-alpha"
    assert report.total_jobs == 1

    # Suite without explicit name falls back to suite ID
    suite_unnamed = SuiteSpec(
        id="suite-beta",
        name=None,
        tasks=[TaskSpec(id="task-2", command="echo beta")],
    )
    cmd2 = SubmitSuiteCommand(suite_spec=suite_unnamed, user_id="bob", elevate=False)
    report2 = pipeline.execute(cmd2)
    assert report2.run_id == "suite-beta"
    assert report2.total_jobs == 1


def test_permission_elevation_for_job_mutation(
    hermetic_cqrs_pipeline: tuple[Any, Any],
) -> None:
    """Verify that cross-tenant job mutation requires positive administrative elevation."""
    _, pipeline = hermetic_cqrs_pipeline
    run_spec = RunSpec(id="run-200", name="Alice Pipeline")
    job = JobSpec(
        id="job-201",
        run_id="run-200",
        name="alice-job",
        command="sleep 100",
        resources=ResourceRequirements(cpus=1, ram_mb=1024),
        tags=["owner:alice"],
    )
    pipeline.execute(SubmitRunCommand(run_spec=run_spec, jobs=[job], user_id="alice"))

    # 1. Alice (natural owner) can hold her own job without elevation
    alice_hold = pipeline.execute(
        HoldJobCommand(job_id="job-201", user_id="alice", elevate=False)
    )
    assert alice_hold.id == "job-201"

    # 2. Bob (unprivileged user or admin without flag) tries to release Alice's job -> Rejected!
    with pytest.raises(PermissionDeniedError) as exc_info:
        pipeline.execute(
            ReleaseJobCommand(job_id="job-201", user_id="bob", elevate=False)
        )
    assert "Permission denied: You are not the owner" in str(exc_info.value)
    assert "--admin / elevate=true" in str(exc_info.value)

    # 3. Bob explicitly elevates permissions (--admin / elevate=True) -> Permitted!
    elevated_release = pipeline.execute(
        ReleaseJobCommand(job_id="job-201", user_id="bob", elevate=True)
    )
    assert elevated_release.id == "job-201"

    # 4. Same for cancel: Bob without elevation fails
    with pytest.raises(PermissionDeniedError):
        pipeline.execute(
            CancelJobCommand(job_id="job-201", user_id="bob", elevate=False)
        )

    # Bob with elevation succeeds
    elevated_cancel = pipeline.execute(
        CancelJobCommand(job_id="job-201", user_id="bob", elevate=True)
    )
    assert elevated_cancel.id == "job-201"

    # 5. Create PTY session on job
    from hexaqueue_core.domain.cqrs import CreatePtySessionCommand

    pty = pipeline.execute(
        CreatePtySessionCommand(
            job_id="job-201",
            session_id="pty-job-201",
            command=["/bin/sh"],
            user_id="alice",
            elevate=False,
        )
    )
    assert pty.is_active is True
    assert pty.job_id == "job-201"


def test_bastion_elevation_enforcement(hermetic_cqrs_pipeline: tuple[Any, Any]) -> None:
    """Verify that node bastion SSH sessions strictly require administrative elevation."""
    _, pipeline = hermetic_cqrs_pipeline

    # Without elevation -> Rejected
    with pytest.raises(PermissionDeniedError) as exc_info:
        pipeline.execute(
            CreateBastionSessionCommand(
                node_id="worker-node-1",
                session_id="bastion-1",
                user_id="alice",
                elevate=False,
            )
        )
    assert "requires explicit administrative elevation" in str(exc_info.value)

    # With elevation -> Granted
    pty_info = pipeline.execute(
        CreateBastionSessionCommand(
            node_id="worker-node-1",
            session_id="bastion-1",
            user_id="alice",
            elevate=True,
        )
    )
    assert pty_info.session_id == "bastion-1"
    assert pty_info.job_id == "bastion-worker-node-1"
    assert pty_info.is_active is True


def test_query_operations(hermetic_cqrs_pipeline: tuple[Any, Any]) -> None:
    """Verify querying jobs, logs, fairshare, queue stats, and nodes."""
    _, pipeline = hermetic_cqrs_pipeline
    run_spec = RunSpec(id="run-300", name="Query Pipeline")
    job = JobSpec(
        id="job-log-1",
        run_id="run-300",
        name="logged-job",
        command="echo logged",
        resources=ResourceRequirements(cpus=1, ram_mb=1024),
        tags=["owner:default"],
    )
    pipeline.execute(SubmitRunCommand(run_spec=run_spec, jobs=[job]))

    jobs = pipeline.execute(ListJobsQuery())
    assert len(jobs) >= 1

    single_job = pipeline.execute(GetJobQuery(job_id="job-log-1"))
    assert single_job.id == "job-log-1"

    logs = pipeline.execute(GetLogsQuery(job_id="job-log-1", tail=1))
    assert len(logs) == 1
    assert "Execution complete" in logs[0].content

    # Full and oversized log tailing
    logs_full = pipeline.execute(GetLogsQuery(job_id="job-log-1", tail=None))
    assert len(logs_full) == 2

    logs_over = pipeline.execute(GetLogsQuery(job_id="job-log-1", tail=10))
    assert len(logs_over) == 2

    stats = pipeline.execute(GetQueueStatsQuery())
    assert stats.active_workers >= 1
    assert stats.running_jobs == 0
    assert stats.pending_jobs >= 1
    assert stats.blocked_jobs == 0
    assert stats.completed_jobs == 0
    assert stats.failed_jobs == 0

    nodes = pipeline.execute(GetNodesQuery())
    assert len(nodes) >= 1

    tree = pipeline.execute(
        GetFairShareTreeQuery(requesting_user="alice", is_admin=True)
    )
    assert tree.root.id == "root"

    # Redaction checks on explainability
    explanation_owner = pipeline.execute(
        ExplainJobQuery(job_id="job-log-1", requesting_user="default", is_admin=False)
    )
    assert explanation_owner.job_id == "job-log-1"
    assert explanation_owner.is_redacted is False

    explanation_other = pipeline.execute(
        ExplainJobQuery(job_id="job-log-1", requesting_user="alice", is_admin=False)
    )
    assert explanation_other.is_redacted is True

    explanation_admin = pipeline.execute(
        ExplainJobQuery(job_id="job-log-1", requesting_user="alice", is_admin=True)
    )
    assert explanation_admin.is_redacted is False


def test_collateral_and_budget_commands(
    hermetic_cqrs_pipeline: tuple[Any, Any],
) -> None:
    """Verify RegisterCollateral and SettleBudget handlers."""
    _, pipeline = hermetic_cqrs_pipeline
    col_bundle = pipeline.execute(
        RegisterCollateralCommand(
            name="model.pt",
            checksum_sha256="a" * 64,
            size_bytes=4096,
        )
    )
    assert col_bundle.filename == "model.pt"
    assert col_bundle.sha256_checksum == "a" * 64

    # Short checksum triggering zfill(64)
    col_short = pipeline.execute(
        RegisterCollateralCommand(
            name="weights.bin",
            checksum_sha256="abc",
            size_bytes=1024,
        )
    )
    assert len(col_short.sha256_checksum) == 64
    assert col_short.sha256_checksum == "abc".zfill(64)

    budget_res = pipeline.execute(
        SettleBudgetCommand(project_id="proj-hpc", amount_cents=1500)
    )
    assert budget_res["status"] == "SETTLED"
    assert budget_res["settled_amount_cents"] == 1500
