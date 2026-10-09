"""Unit tests for job lifecycle mutations, inspection, and PTY sessions."""

from typing import Any

import pytest

from hexaqueue_core.domain.cqrs import (
    CancelJobCommand,
    CreatePtySessionCommand,
    ExplainJobQuery,
    GetJobQuery,
    HoldJobCommand,
    ListJobsQuery,
    ReleaseJobCommand,
    SubmitRunCommand,
)
from hexaqueue_core.domain.exceptions import PermissionDeniedError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.run import RunSpec


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

    # 2. Bob (unprivileged user) tries to release Alice's job -> Rejected!
    with pytest.raises(PermissionDeniedError) as exc_info:
        pipeline.execute(
            ReleaseJobCommand(job_id="job-201", user_id="bob", elevate=False)
        )
    err_text = str(exc_info.value)
    assert "Permission denied: You are not the owner" in err_text
    assert "--admin / elevate=true" in err_text

    # 3. Bob explicitly elevates permissions -> Permitted!
    elevated_release = pipeline.execute(
        ReleaseJobCommand(job_id="job-201", user_id="bob", elevate=True)
    )
    assert elevated_release.id == "job-201"

    # 4. Bob without elevation fails to cancel
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


def test_job_queries_and_explainability(
    hermetic_cqrs_pipeline: tuple[Any, Any],
) -> None:
    """Verify GetJobQuery, ListJobsQuery, and ExplainJobQuery with redaction."""
    _, pipeline = hermetic_cqrs_pipeline
    run_spec = RunSpec(id="run-exp-1", name="Explain Pipeline")
    job = JobSpec(
        id="job-exp-1",
        run_id="run-exp-1",
        name="explain-job",
        command="sleep 10",
        resources=ResourceRequirements(cpus=1, ram_mb=1024),
        tags=["owner:alice"],
    )
    pipeline.execute(SubmitRunCommand(run_spec=run_spec, jobs=[job], user_id="alice"))

    # GetJobQuery as owner
    j_owner = pipeline.execute(
        GetJobQuery(job_id="job-exp-1", user_id="alice", elevate=False)
    )
    assert j_owner.id == "job-exp-1"

    # GetJobQuery as non-owner without elevate -> rejected
    with pytest.raises(PermissionDeniedError):
        pipeline.execute(GetJobQuery(job_id="job-exp-1", user_id="bob", elevate=False))

    # ListJobsQuery filtering
    jobs_alice = pipeline.execute(ListJobsQuery(user_id="alice", elevate=False))
    assert len(jobs_alice) >= 1

    jobs_bob = pipeline.execute(ListJobsQuery(user_id="bob", elevate=False))
    bob_matching = [j for j in jobs_bob if j.id == "job-exp-1"]
    assert len(bob_matching) == 0

    # Explainability: owner sees unredacted
    exp_owner = pipeline.execute(
        ExplainJobQuery(job_id="job-exp-1", requesting_user="alice", is_admin=False)
    )
    assert exp_owner.is_redacted is False

    # Explainability: other sees redacted
    exp_other = pipeline.execute(
        ExplainJobQuery(job_id="job-exp-1", requesting_user="bob", is_admin=False)
    )
    assert exp_other.is_redacted is True

    # Explainability: admin sees unredacted
    exp_admin = pipeline.execute(
        ExplainJobQuery(job_id="job-exp-1", requesting_user="bob", is_admin=True)
    )
    assert exp_admin.is_redacted is False
