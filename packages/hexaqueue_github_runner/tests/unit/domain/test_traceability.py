"""Unit tests for traceability and execution summary annotation."""

from hexaqueue_github_runner.domain.traceability import JobSummaryAnnotation


def test_job_summary_annotation_markdown() -> None:
    """Test generating markdown summary from JobSummaryAnnotation."""
    annotation = JobSummaryAnnotation(
        job_id="job-1234",
        run_id="run-5678",
        workflow_job_id=9999,
        execution_seconds=45.5,
        credit_burn=0.125,
        status="COMPLETED",
        node_id="node-gpu-01",
        gpu_model="h100",
    )
    md = annotation.to_markdown_summary()
    assert "### ⚡ Hexaqueue Runner Execution Report" in md
    assert "job-1234" in md
    assert "0.1250 HQ" in md
    assert "node-gpu-01" in md
    assert "h100" in md
