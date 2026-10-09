"""Tests for job inspection, lifecycle mutation, explainability, and PTY endpoints."""

from fastapi.testclient import TestClient


def test_jobs_list_and_get(hermetic_api_client: TestClient) -> None:
    """Verify jobs listing and individual job metadata lookup."""
    client = hermetic_api_client

    # List jobs
    resp_list = client.get("/v1/jobs", headers={"X-Hexaqueue-User": "alice"})
    list_code = resp_list.status_code
    assert list_code == 200
    jobs = resp_list.json()
    job_count = len(jobs)
    assert job_count >= 1

    # Get single job
    resp_get = client.get("/v1/jobs/job-api-1", headers={"X-Hexaqueue-User": "alice"})
    get_code = resp_get.status_code
    assert get_code == 200
    job = resp_get.json()
    assert job["id"] == "job-api-1"


def test_jobs_hold_release_and_cancel(hermetic_api_client: TestClient) -> None:
    """Verify job hold, release, and cancellation lifecycle mutations."""
    client = hermetic_api_client

    # 1. Hold job
    resp_hold = client.post(
        "/v1/jobs/job-api-1/hold", headers={"X-Hexaqueue-User": "alice"}
    )
    hold_code = resp_hold.status_code
    assert hold_code == 200
    held_job = resp_hold.json()
    assert held_job["status"]["state"] == "BLOCKED"

    # 2. Release job
    resp_release = client.post(
        "/v1/jobs/job-api-1/release", headers={"X-Hexaqueue-User": "alice"}
    )
    release_code = resp_release.status_code
    assert release_code == 200
    released_job = resp_release.json()
    assert released_job["status"]["state"] == "PENDING"

    # 3. Cancel job
    resp_cancel = client.post(
        "/v1/jobs/job-api-1/cancel", headers={"X-Hexaqueue-User": "alice"}
    )
    cancel_code = resp_cancel.status_code
    assert cancel_code == 200
    cancelled_job = resp_cancel.json()
    assert cancelled_job["status"]["state"] == "DONE"
    assert cancelled_job["status"]["outcome"] == "CANCELLED"


def test_jobs_explain_and_pty(hermetic_api_client: TestClient) -> None:
    """Verify scheduling explainability report and PTY attach session creation."""
    client = hermetic_api_client

    # Explain job
    resp_explain = client.get(
        "/v1/jobs/job-api-1/explain", headers={"X-Hexaqueue-User": "alice"}
    )
    explain_code = resp_explain.status_code
    assert explain_code == 200
    explain_data = resp_explain.json()
    assert "priority_breakdown" in explain_data

    # Create PTY session
    resp_pty = client.post(
        "/v1/jobs/job-api-1/pty",
        json={
            "session_id": "pty-sess-1",
            "rows": 30,
            "cols": 100,
            "command": ["/bin/bash"],
        },
        headers={"X-Hexaqueue-User": "alice"},
    )
    pty_code = resp_pty.status_code
    assert pty_code == 200
    pty_data = resp_pty.json()
    assert pty_data["session_id"] == "pty-sess-1"
    assert pty_data["job_id"] == "job-api-1"
    assert pty_data["user_id"] == "alice"
    assert pty_data["is_active"] is True
