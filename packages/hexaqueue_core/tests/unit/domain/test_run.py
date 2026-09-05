"""Tests for RunSpec domain model."""

import pytest

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import (
    JobState,
    JobStatus,
    RunOutcome,
    RunState,
    TerminalOutcome,
)
from hexaqueue_core.domain.run import RunSpec


def test_run_spec_defaults() -> None:
    """Verify RunSpec generation and properties."""
    run = RunSpec(id="run-1", name="pipeline-1", tags=["ci", "test"])
    assert run.id == "run-1"
    assert run.name == "pipeline-1"
    assert run.tags == ["ci", "test"]
    assert run.state == RunState.DONE
    assert run.outcome == RunOutcome.SUCCEEDED


def test_run_spec_empty_id_fails() -> None:
    """Verify RunSpec requires non-empty id."""
    with pytest.raises(ValueError, match="Run id cannot be empty"):
        RunSpec(id="   ", name="pipeline-1")


def test_run_spec_outcome_computation() -> None:
    """Verify RunSpec computes outcome when done."""
    j1 = JobSpec(
        id="j1",
        run_id="run-1",
        name="job-1",
        command="echo",
        status=JobStatus(state=JobState.DONE, outcome=TerminalOutcome.COMPLETED),
    )
    run = RunSpec(id="run-1", name="pipeline-1", jobs=[j1])
    assert run.state == RunState.DONE
    assert run.outcome == RunOutcome.SUCCEEDED
