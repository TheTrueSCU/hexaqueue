"""Tests for log streaming and presigned object storage endpoints."""

from fastapi.testclient import TestClient


def test_logs_tailing_and_presigned_flow(hermetic_api_client: TestClient) -> None:
    """Verify in-memory log tailing and direct presigned storage upload/download flow."""
    client = hermetic_api_client

    # 1. In-memory log tailing
    resp_logs = client.get(
        "/v1/jobs/job-api-1/logs?tail=2", headers={"X-Hexaqueue-User": "alice"}
    )
    logs_code = resp_logs.status_code
    assert logs_code == 200
    chunks = resp_logs.json()
    chunk_count = len(chunks)
    assert chunk_count == 2

    # 2. Request presigned upload URL
    resp_upload = client.post(
        "/v1/jobs/job-api-1/logs/upload-url",
        json={
            "job_id": "job-api-1",
            "outcome": "COMPLETED",
            "size_bytes": 1024,
            "expires_in_seconds": 300,
        },
        headers={"X-Hexaqueue-User": "alice"},
    )
    upload_code = resp_upload.status_code
    assert upload_code == 200
    token_data = resp_upload.json()
    assert token_data["job_id"] == "job-api-1"
    assert "upload/logs/job-api-1/stdout_stderr.log" in token_data["upload_url"]

    # 3. Notify complete
    resp_complete = client.post(
        "/v1/jobs/job-api-1/logs/complete",
        json={
            "job_id": "job-api-1",
            "storage_key": token_data["storage_key"],
            "sha256_checksum": "c" * 64,
            "size_bytes": 1024,
        },
        headers={"X-Hexaqueue-User": "alice"},
    )
    complete_code = resp_complete.status_code
    assert complete_code == 200
    assert resp_complete.json()["status"] == "recorded"

    # 4. Get download URL
    resp_dl = client.get(
        "/v1/jobs/job-api-1/logs/download-url?expires_in_seconds=600",
        headers={"X-Hexaqueue-User": "alice"},
    )
    dl_code = resp_dl.status_code
    assert dl_code == 200
    dl_data = resp_dl.json()
    assert dl_data["job_id"] == "job-api-1"
    assert "download/logs/job-api-1/stdout_stderr.log" in dl_data["download_url"]
