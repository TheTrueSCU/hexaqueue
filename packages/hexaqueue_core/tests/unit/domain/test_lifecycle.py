"""Unit tests for Job and Run lifecycle state transitions and roll-ups."""

import pytest

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import (
    JobState,
    JobStatus,
    RunOutcome,
    RunState,
    TerminalOutcome,
    can_transition_job,
    compute_run_outcome,
    compute_run_state,
)
from hexaqueue_core.domain.run import RunSpec


def test_valid_job_transitions():
    """Verify legal state transitions in the state machine."""
    assert can_transition_job(JobState.SUBMITTED, JobState.PENDING)
    assert can_transition_job(JobState.SUBMITTED, JobState.BLOCKED)
    assert can_transition_job(JobState.BLOCKED, JobState.PENDING)
    assert can_transition_job(JobState.PENDING, JobState.PROVISIONING)
    assert can_transition_job(JobState.PENDING, JobState.RUNNING)
    assert can_transition_job(JobState.PROVISIONING, JobState.RUNNING)
    assert can_transition_job(JobState.RUNNING, JobState.CLEANUP)
    assert can_transition_job(JobState.CLEANUP, JobState.DONE)


def test_invalid_job_transitions():
    """Verify illegal transitions are disallowed."""
    assert not can_transition_job(JobState.SUBMITTED, JobState.RUNNING)
    assert not can_transition_job(JobState.BLOCKED, JobState.RUNNING)
    assert not can_transition_job(JobState.DONE, JobState.RUNNING)


def test_job_status_invariant():
    """Verify JobStatus enforces outcome presence only on DONE state."""
    with pytest.raises(
        ValueError, match="Terminal outcome must be provided when job state is DONE"
    ):
        JobStatus(state=JobState.DONE, outcome=None)

    with pytest.raises(
        ValueError, match="Terminal outcome cannot be set when job state is PENDING"
    ):
        JobStatus(state=JobState.PENDING, outcome=TerminalOutcome.COMPLETED)


def test_run_roll_up_all_submitted():
    """All jobs submitted -> Run is SUBMITTED."""
    assert (
        compute_run_state([JobState.SUBMITTED, JobState.SUBMITTED])
        == RunState.SUBMITTED
    )


def test_run_roll_up_all_blocked():
    """All uncompleted jobs blocked -> Run is BLOCKED."""
    assert compute_run_state([JobState.BLOCKED, JobState.BLOCKED]) == RunState.BLOCKED


def test_run_roll_up_active_execution():
    """Any job pending/running/cleanup -> Run is RUNNING."""
    assert compute_run_state([JobState.BLOCKED, JobState.RUNNING]) == RunState.RUNNING
    assert compute_run_state([JobState.SUBMITTED, JobState.PENDING]) == RunState.RUNNING


def test_run_roll_up_all_done():
    """All jobs done -> Run is DONE."""
    assert compute_run_state([JobState.DONE, JobState.DONE]) == RunState.DONE


def test_run_outcome_computation():
    """Verify aggregate RunOutcome computation."""
    assert (
        compute_run_outcome([TerminalOutcome.COMPLETED, TerminalOutcome.COMPLETED])
        == RunOutcome.SUCCEEDED
    )
    assert (
        compute_run_outcome([TerminalOutcome.COMPLETED, TerminalOutcome.FAILED])
        == RunOutcome.PARTIALLY_FAILED
    )
    assert (
        compute_run_outcome([TerminalOutcome.FAILED, TerminalOutcome.FAILED])
        == RunOutcome.FAILED
    )
    assert (
        compute_run_outcome([TerminalOutcome.CANCELLED, TerminalOutcome.CANCELLED])
        == RunOutcome.CANCELLED
    )


def test_run_spec_projection():
    """Verify RunSpec computes state and outcome dynamically."""
    j1 = JobSpec(
        id="j1",
        run_id="r1",
        name="Test 1",
        command="./run.sh",
        status=JobStatus(state=JobState.DONE, outcome=TerminalOutcome.COMPLETED),
    )
    j2 = JobSpec(
        id="j2",
        run_id="r1",
        name="Test 2",
        command="./run.sh",
        status=JobStatus(state=JobState.DONE, outcome=TerminalOutcome.FAILED),
    )
    run = RunSpec(id="r1", name="Nightly Regression", jobs=[j1, j2])

    assert run.state == RunState.DONE
    assert run.outcome == RunOutcome.PARTIALLY_FAILED
