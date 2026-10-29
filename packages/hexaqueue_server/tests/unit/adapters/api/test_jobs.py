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


def test_jobs_task_queue_endpoints(hermetic_api_client: TestClient) -> None:
    """Verify task queue enqueue, lease, complete, and fail endpoints."""
    client = hermetic_api_client

    # 1. Enqueue task via /api/v1/jobs
    enqueue_payload = {
        "task_name": "render_video",
        "payload": {"resolution": "1080p"},
        "priority": 5,
        "max_attempts": 2,
        "queue": "default",
    }
    resp_enq = client.post(
        "/api/v1/jobs",
        json=enqueue_payload,
        headers={"X-Hexaqueue-User": "alice"},
    )
    enq_code = resp_enq.status_code
    assert enq_code == 201
    enq_data = resp_enq.json()
    task_id = enq_data["id"]
    assert enq_data["task_name"] == "render_video"
    assert enq_data["state"] == "PENDING"
    assert enq_data["priority"] == 5

    # 2. Lease task via /api/v1/jobs/lease
    lease_payload = {
        "worker_id": "worker-gpu-1",
        "task_names": ["render_video"],
        "lease_duration_seconds": 60.0,
    }
    resp_lease = client.post(
        "/api/v1/jobs/lease",
        json=lease_payload,
        headers={"X-Hexaqueue-User": "alice"},
    )
    lease_code = resp_lease.status_code
    assert lease_code in (200, 204)
    if lease_code == 200:
        leased = resp_lease.json()
        assert leased["lease_owner"] == "worker-gpu-1"
        assert leased["state"] == "RUNNING"

    # 3. Complete task via /api/v1/jobs/{task_id}/complete
    resp_comp = client.post(
        f"/api/v1/jobs/{task_id}/complete",
        json={"worker_id": "worker-gpu-1"},
        headers={"X-Hexaqueue-User": "alice"},
    )
    comp_code = resp_comp.status_code
    assert comp_code == 200
    assert resp_comp.json()["status"] == "completed"

    # 4. Fail task via /api/v1/jobs/{task_id}/fail
    resp_fail = client.post(
        f"/api/v1/jobs/{task_id}/fail",
        json={"worker_id": "worker-gpu-1", "error": "OutOfMemory"},
        headers={"X-Hexaqueue-User": "alice"},
    )
    fail_code = resp_fail.status_code
    assert fail_code == 200
    assert resp_fail.json()["status"] == "failed"


def test_hexastack_task_queue_adapter_integration(
    hermetic_api_client: TestClient,
) -> None:
    """Verify Hexastack's HexaqueueTaskQueueAdapter communicates with server endpoints."""
    from hexastack_events.adapters.tasks.hexaqueue import HexaqueueTaskQueueAdapter

    client = hermetic_api_client
    adapter = HexaqueueTaskQueueAdapter(
        cluster_url="http://testserver",
        client=client,
    )

    # Enqueue task
    record = adapter.enqueue(
        task_name="send_digest",
        payload={"user_id": "user-42"},
        priority=10,
    )
    rec_id = record.id
    rec_name = record.task_name
    assert rec_id.startswith("task_")
    assert rec_name == "send_digest"

    # Complete task
    adapter.complete(record.id)
