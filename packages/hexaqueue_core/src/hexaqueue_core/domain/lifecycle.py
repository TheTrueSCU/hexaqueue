"""Lifecycle state machines and terminal status models for jobs and aggregated runs.

Notes/Architectural Intent:
    Defines the discrete lifecycle states, valid state transitions, and
    deterministic roll-up logic for hierarchical runs and concrete leaf jobs.
    Invariants ensure that jobs cannot jump states arbitrarily and that
    run states are mathematical pure projections of constituent job states.
"""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JobState(StrEnum):
    r"""Discrete lifecycle states for a scheduled leaf job.

    State Progression:
        SUBMITTED -> BLOCKED -> PENDING -> [PROVISIONING] -> RUNNING -> CLEANUP -> DONE
           \-> (Prerequisites met immediately) -> PENDING
    """

    SUBMITTED = "SUBMITTED"
    BLOCKED = "BLOCKED"
    PENDING = "PENDING"
    PROVISIONING = "PROVISIONING"
    RUNNING = "RUNNING"
    CLEANUP = "CLEANUP"
    DONE = "DONE"


class TerminalOutcome(StrEnum):
    """Terminal completion sub-status when a job or run enters the DONE state."""

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    PREEMPTED = "PREEMPTED"


class RunState(StrEnum):
    """Aggregated lifecycle state for a root parent Run containing a tree of jobs.

    Roll-Up Rules:
        - SUBMITTED: All jobs are in SUBMITTED.
        - BLOCKED: All uncompleted jobs are BLOCKED.
        - RUNNING: At least one job is PENDING, PROVISIONING, RUNNING, or CLEANUP.
        - DONE: All leaf jobs have reached the DONE state.
    """

    SUBMITTED = "SUBMITTED"
    BLOCKED = "BLOCKED"
    RUNNING = "RUNNING"
    DONE = "DONE"


class RunOutcome(StrEnum):
    """Aggregated terminal outcome for a completed Run."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIALLY_FAILED = "PARTIALLY_FAILED"
    CANCELLED = "CANCELLED"


# Valid direct transitions for a Job
VALID_JOB_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.SUBMITTED: {JobState.BLOCKED, JobState.PENDING, JobState.DONE},
    JobState.BLOCKED: {JobState.PENDING, JobState.DONE},
    JobState.PENDING: {
        JobState.PROVISIONING,
        JobState.RUNNING,
        JobState.BLOCKED,
        JobState.DONE,
    },
    JobState.PROVISIONING: {JobState.RUNNING, JobState.PENDING, JobState.DONE},
    JobState.RUNNING: {JobState.CLEANUP, JobState.DONE},
    JobState.CLEANUP: {JobState.DONE},
    JobState.DONE: set(),
}


def can_transition_job(from_state: JobState, to_state: JobState) -> bool:
    """Verify if a job state transition is legally permissible.

    Args:
        from_state: Current state of the job.
        to_state: Target transition state.

    Returns:
        True if the transition is allowed by the lifecycle state machine, False otherwise.
    """
    if from_state == to_state:
        return True
    return to_state in VALID_JOB_TRANSITIONS.get(from_state, set())


def compute_run_state(job_states: list[JobState]) -> RunState:
    """Compute the aggregated RunState from a collection of leaf job states.

    Args:
        job_states: List of JobState values for all leaf jobs in the run.

    Returns:
        The aggregated RunState.

    Notes/Architectural Intent:
        Guarantees deterministic roll-up behavior across arbitrary tree depths.
    """
    if not job_states:
        return RunState.DONE

    # If all jobs are in DONE state -> Run is DONE
    if all(s == JobState.DONE for s in job_states):
        return RunState.DONE

    # If all jobs are in SUBMITTED state -> Run is SUBMITTED
    if all(s == JobState.SUBMITTED for s in job_states):
        return RunState.SUBMITTED

    # If active execution / scheduling is in flight
    active_states = {
        JobState.PENDING,
        JobState.PROVISIONING,
        JobState.RUNNING,
        JobState.CLEANUP,
    }
    if any(s in active_states for s in job_states):
        return RunState.RUNNING

    # If all remaining non-done jobs are blocked
    uncompleted = [s for s in job_states if s != JobState.DONE]
    if uncompleted and all(s == JobState.BLOCKED for s in uncompleted):
        return RunState.BLOCKED

    return RunState.RUNNING


def compute_run_outcome(job_outcomes: list[TerminalOutcome]) -> RunOutcome:
    """Compute the aggregate terminal outcome for a completed run.

    Args:
        job_outcomes: Terminal outcomes of all leaf jobs in the run.

    Returns:
        The aggregated RunOutcome.
    """
    if not job_outcomes:
        return RunOutcome.SUCCEEDED

    if all(o == TerminalOutcome.COMPLETED for o in job_outcomes):
        return RunOutcome.SUCCEEDED

    if all(
        o in (TerminalOutcome.CANCELLED, TerminalOutcome.PREEMPTED)
        for o in job_outcomes
    ):
        return RunOutcome.CANCELLED

    if all(
        o in (TerminalOutcome.FAILED, TerminalOutcome.TIMED_OUT) for o in job_outcomes
    ):
        return RunOutcome.FAILED

    # Mix of COMPLETED and FAILED/CANCELLED
    return RunOutcome.PARTIALLY_FAILED


class JobStatus(BaseModel):
    """Value object capturing current state, terminal outcome, and transition history.

    Args:
        state: Current JobState.
        outcome: TerminalOutcome (set only if state is DONE).
        reason: Optional human-readable explanation of the current state or failure.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: JobState = Field(
        default=JobState.SUBMITTED, description="Current lifecycle state"
    )
    outcome: TerminalOutcome | None = Field(
        default=None, description="Terminal outcome if DONE"
    )
    reason: str | None = Field(
        default=None, description="Detailed state or failure reason"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate state and outcome consistency invariants."""
        if self.state == JobState.DONE and self.outcome is None:
            msg = "Terminal outcome must be provided when job state is DONE"
            raise ValueError(msg)
        if self.state != JobState.DONE and self.outcome is not None:
            msg = f"Terminal outcome cannot be set when job state is {self.state}"
            raise ValueError(msg)
        return self
