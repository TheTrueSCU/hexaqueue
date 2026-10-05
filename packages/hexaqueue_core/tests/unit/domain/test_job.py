"""Tests for JobSpec domain model."""

import pytest

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState


def test_job_spec_defaults() -> None:
    """Verify JobSpec instantiation and default values."""
    job = JobSpec(id="job-1", run_id="run-1", name="echo-job", command="echo")
    assert job.id == "job-1"
    assert job.run_id == "run-1"
    assert job.name == "echo-job"
    assert job.command == "echo"
    assert job.args == []
    assert job.env == {}
    assert job.collateral_ids == []
    assert job.tags == []
    assert job.resources is not None
    assert job.state == JobState.SUBMITTED
    assert job.outcome is None


def test_job_spec_empty_validation_fails() -> None:
    """Verify JobSpec requires non-empty id and command."""
    with pytest.raises(ValueError, match="Job id cannot be empty"):
        JobSpec(id="  ", run_id="run-1", name="invalid", command="echo")

    with pytest.raises(ValueError, match="Job command cannot be empty"):
        JobSpec(id="job-1", run_id="run-1", name="invalid", command="   ")
