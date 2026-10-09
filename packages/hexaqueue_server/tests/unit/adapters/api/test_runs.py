"""Tests for pipeline run and test suite REST endpoints."""

from fastapi.testclient import TestClient


def test_runs_submit_status_and_cancel(hermetic_api_client: TestClient) -> None:
    """Verify run submission, status retrieval, and cancellation via REST API."""
    client = hermetic_api_client

    # 1. Submit run
    payload = {
        "run_spec": {"id": "run-test-api", "name": "test-run", "tags": ["owner:bob"]},
        "jobs": [
            {
                "id": "job-b1",
                "run_id": "run-test-api",
                "name": "task-b1",
                "command": "python script.py",
                "tags": ["owner:bob"],
            }
        ],
        "dependencies": {},
    }
    resp = client.post("/v1/runs", json=payload, headers={"X-Hexaqueue-User": "bob"})
    status_code = resp.status_code
    assert status_code == 201
    data = resp.json()
    assert data["run_id"] == "run-test-api"
    assert data["total_jobs"] == 1

    # 2. Get status
    resp_get = client.get("/v1/runs/run-test-api", headers={"X-Hexaqueue-User": "bob"})
    get_code = resp_get.status_code
    assert get_code == 200
    assert resp_get.json()["run_id"] == "run-test-api"

    # 3. Cancel run
    resp_cancel = client.post(
        "/v1/runs/run-test-api/cancel", headers={"X-Hexaqueue-User": "bob"}
    )
    cancel_code = resp_cancel.status_code
    assert cancel_code == 200
    cancel_data = resp_cancel.json()
    assert cancel_data["state"] == "DONE"
    assert cancel_data["outcome"] == "CANCELLED"


def test_runs_submit_suite(hermetic_api_client: TestClient) -> None:
    """Verify hierarchical test suite submission compiles and schedules."""
    client = hermetic_api_client
    suite_payload = {
        "suite_spec": {
            "id": "suite-api-1",
            "name": "integration-suite",
            "tasks": [
                {
                    "id": "task-lint",
                    "name": "lint",
                    "command": "ruff check .",
                },
                {
                    "id": "task-typecheck",
                    "name": "typecheck",
                    "command": "ty check .",
                    "depends_on": ["task-lint"],
                },
            ],
        }
    }
    resp = client.post(
        "/v1/suites", json=suite_payload, headers={"X-Hexaqueue-User": "alice"}
    )
    status_code = resp.status_code
    assert status_code == 201
    data = resp.json()
    assert data["run_id"] == "suite-api-1"
    assert data["total_jobs"] == 2


def test_runs_stream_sse(hermetic_api_client: TestClient) -> None:
    """Verify Server-Sent Events stream emits run status pulses."""
    client = hermetic_api_client
    with client.stream(
        "GET",
        "/v1/runs/run-api-seed/stream?poll_interval=0.05&max_events=1&timeout=1.0",
        headers={"X-Hexaqueue-User": "alice"},
    ) as resp:
        code = resp.status_code
        assert code == 200
        lines = list(resp.iter_lines())
        has_status = any("event: run_status" in line for line in lines)
        assert has_status is True
