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


def test_job_summary_annotation_free_tier() -> None:
    """Test generating markdown summary for zero-cost free tier runner."""
    annotation = JobSummaryAnnotation(
        job_id="job-free-1",
        run_id="run-free-1",
        workflow_job_id=8888,
        execution_seconds=120.0,
        credit_burn=0.0,
        cost_usd=0.0,
        is_free_tier=True,
        provider="OCI",
        status="COMPLETED",
        node_id="hq-gh-oci-test-repo-8888-abcd",
    )
    md = annotation.to_markdown_summary()
    assert "job-free-1" in md
    assert "$0.00 (Verified $0.00 Free Tier)" in md
    assert "- **Cloud Provider**: `OCI`" in md
    assert "Single-Job Isolation" in md
    assert "hq-gh-oci-test-repo-8888-abcd" in md
