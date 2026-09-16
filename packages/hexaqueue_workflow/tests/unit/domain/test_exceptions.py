"""Tests for domain exceptions."""

from hexaqueue_workflow.domain.exceptions import (
    ArtifactStagingError,
    HexaqueueWorkflowError,
    JobExecutionFailedError,
    StepMappingNotFoundError,
)


def test_hierarchy_and_messages() -> None:
    """Verify exception hierarchy and string representation."""
    base_err = HexaqueueWorkflowError("base error")
    assert isinstance(base_err, Exception)

    staging_err = ArtifactStagingError("staging failed")
    assert isinstance(staging_err, HexaqueueWorkflowError)

    mapping_err = StepMappingNotFoundError("mapping missing")
    assert isinstance(mapping_err, HexaqueueWorkflowError)

    job_err = JobExecutionFailedError(job_id="job-123", reason="oom killed")
    assert isinstance(job_err, HexaqueueWorkflowError)
    assert job_err.job_id == "job-123"
    assert job_err.reason == "oom killed"
    msg = str(job_err)
    assert "job-123" in msg
    assert "oom killed" in msg


def test_job_execution_failed_error_default_reason() -> None:
    """Verify JobExecutionFailedError with default reason."""
    err = JobExecutionFailedError(job_id="job-456")
    msg = str(err)
    assert "unknown reason" in msg
