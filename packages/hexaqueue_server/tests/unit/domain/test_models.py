"""Tests for hexaqueue_server domain models."""

from datetime import UTC, datetime

import pytest

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import RunOutcome, RunState
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission


def test_run_submission_valid() -> None:
    """Verify RunSubmission creation and validation with valid dependencies."""
    run = RunSpec(id="run-1", name="test-run")
    j1 = JobSpec(id="j1", run_id=run.id, name="job-1", command="echo", args=["1"])
    j2 = JobSpec(id="j2", run_id=run.id, name="job-2", command="echo", args=["2"])

    submission = RunSubmission(
        run_spec=run,
        jobs=[j1, j2],
        dependencies={j2.id: [j1.id]},
    )
    assert submission.run_spec.id == run.id
    assert len(submission.jobs) == 2
    assert submission.dependencies[j2.id] == [j1.id]


def test_run_submission_invalid_child() -> None:
    """Verify RunSubmission rejects unknown child job ID."""
    run = RunSpec(id="run-1", name="test-run")
    j1 = JobSpec(id="j1", run_id=run.id, name="job-1", command="echo", args=["1"])

    with pytest.raises(ValueError, match="Dependency child job 'unknown' not found"):
        RunSubmission(
            run_spec=run,
            jobs=[j1],
            dependencies={"unknown": [j1.id]},
        )


def test_run_submission_invalid_parent() -> None:
    """Verify RunSubmission rejects unknown parent job ID."""
    run = RunSpec(id="run-1", name="test-run")
    j1 = JobSpec(id="j1", run_id=run.id, name="job-1", command="echo", args=["1"])

    with pytest.raises(ValueError, match="Dependency parent job 'unknown' not found"):
        RunSubmission(
            run_spec=run,
            jobs=[j1],
            dependencies={j1.id: ["unknown"]},
        )


def test_run_status_report() -> None:
    """Verify RunStatusReport serialization and fields."""
    now = datetime.now(UTC)
    report = RunStatusReport(
        run_id="run-1",
        state=RunState.DONE,
        outcome=RunOutcome.SUCCEEDED,
        total_jobs=3,
        completed_jobs=3,
        failed_jobs=0,
        running_jobs=0,
        pending_jobs=0,
        created_at=now,
    )
    assert report.run_id == "run-1"
    assert report.state == RunState.DONE
    assert report.outcome == RunOutcome.SUCCEEDED
    assert report.total_jobs == 3
    assert report.completed_jobs == 3
    assert report.failed_jobs == 0
    assert report.running_jobs == 0
    assert report.pending_jobs == 0
    assert report.created_at == now
    assert report.updated_at is not None
