"""Unit tests for logs and presigned storage CQRS handlers."""

from typing import Any

from hexaqueue_core.domain.cqrs import (
    GetJobLogDownloadUrlQuery,
    GetLogsQuery,
    NotifyLogUploadCompleteCommand,
    RequestLogUploadUrlCommand,
)
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.retention import LogRetentionTier


def test_get_logs_query(hermetic_cqrs_pipeline: tuple[Any, Any]) -> None:
    """Verify querying log chunks with various tailing parameters."""
    _, pipeline = hermetic_cqrs_pipeline

    logs_one = pipeline.execute(GetLogsQuery(job_id="job-log-1", tail=1, elevate=True))
    assert len(logs_one) == 1
    assert "Execution complete" in logs_one[0].content

    logs_full = pipeline.execute(
        GetLogsQuery(job_id="job-log-1", tail=None, elevate=True)
    )
    assert len(logs_full) == 2

    logs_over = pipeline.execute(
        GetLogsQuery(job_id="job-log-1", tail=10, elevate=True)
    )
    assert len(logs_over) == 2


def test_presigned_log_flow(hermetic_cqrs_pipeline: tuple[Any, Any]) -> None:
    """Verify presigned upload token request, completion callback, and download URL generation."""
    _, pipeline = hermetic_cqrs_pipeline

    # 1. Request presigned upload token
    token = pipeline.execute(
        RequestLogUploadUrlCommand(
            job_id="job-log-1",
            outcome=TerminalOutcome.COMPLETED,
            size_bytes=512,
            expires_in_seconds=300,
            elevate=True,
        )
    )
    upload_url = token.upload_url
    assert "upload/logs/job-log-1/stdout_stderr.log" in upload_url
    assert token.retention_policy.tier == LogRetentionTier.SHORT_PASS

    # 2. Complete notification
    complete_res = pipeline.execute(
        NotifyLogUploadCompleteCommand(
            job_id="job-log-1",
            storage_key=token.storage_key,
            sha256_checksum="b" * 64,
            size_bytes=512,
        )
    )
    assert complete_res["status"] == "recorded"

    # 3. Request presigned download URL
    dl = pipeline.execute(
        GetJobLogDownloadUrlQuery(
            job_id="job-log-1",
            expires_in_seconds=900,
            elevate=True,
        )
    )
    dl_url = dl.download_url
    assert "download/logs/job-log-1/stdout_stderr.log" in dl_url
