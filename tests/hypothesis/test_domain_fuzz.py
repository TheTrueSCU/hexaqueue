"""Property-based invariant fuzzing tests for Job and Run domain models."""

from hypothesis import given
from hypothesis import strategies as st

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, RunState, compute_run_state
from hexaqueue_core.testing.synthetic import (
    job_spec_strategy,
    resource_requirements_strategy,
)


@given(resource_requirements_strategy())
def test_resource_requirements_invariants(res):
    """Resource requirements always satisfy non-negative bounds."""
    assert res.cpus >= 1
    assert res.ram_mb >= 128
    assert res.gpus >= 0
    assert res.scratch_mb >= 0
    assert res.walltime_seconds >= 10


@given(job_spec_strategy())
def test_job_spec_invariants(job: JobSpec):
    """JobSpec maintains structural invariants across randomized generations."""
    assert len(job.id.strip()) > 0
    assert len(job.command.strip()) > 0
    assert job.state in JobState


@given(st.lists(st.sampled_from(list(JobState)), min_size=1, max_size=50))
def test_run_roll_up_fuzz(job_states: list[JobState]):
    """RunState roll-up produces a valid RunState for any combination of job states."""
    run_state = compute_run_state(job_states)
    assert run_state in RunState

    # Fundamental Invariant: If ALL jobs are DONE, run MUST be DONE
    if all(s == JobState.DONE for s in job_states):
        assert run_state == RunState.DONE

    # Fundamental Invariant: If ANY job is active, run MUST be RUNNING
    if any(
        s
        in (JobState.PENDING, JobState.PROVISIONING, JobState.RUNNING, JobState.CLEANUP)
        for s in job_states
    ):
        assert run_state == RunState.RUNNING
