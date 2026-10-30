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


def test_runs_workflow_aliases_and_simulation(hermetic_api_client: TestClient) -> None:
    """Verify workflow orchestrator aliases /abort, /resume, /rewind, and /simulate."""
    client = hermetic_api_client

    # 0. Submit a run first
    payload = {
        "run_spec": {
            "id": "run-alias-test",
            "name": "alias-run",
            "tags": ["owner:bob"],
        },
        "jobs": [
            {
                "id": "job-alias-1",
                "run_id": "run-alias-test",
                "name": "step-alias",
                "command": "echo alias",
                "tags": ["owner:bob"],
            }
        ],
        "dependencies": {},
    }
    client.post("/v1/runs", json=payload, headers={"X-Hexaqueue-User": "bob"})

    # 1. Simulate run
    resp_sim = client.post(
        "/v1/runs/simulate", json={}, headers={"X-Hexaqueue-User": "bob"}
    )
    sim_code = resp_sim.status_code
    assert sim_code == 200
    assert resp_sim.json()["status"] == "COMPLETED"

    # 2. Resume run
    resp_res = client.post(
        "/api/v1/runs/run-alias-test/resume", headers={"X-Hexaqueue-User": "bob"}
    )
    res_code = resp_res.status_code
    assert res_code == 200
    assert resp_res.json()["run_id"] == "run-alias-test"

    # 3. Rewind run
    resp_rew = client.post(
        "/api/v1/runs/run-alias-test/rewind", headers={"X-Hexaqueue-User": "bob"}
    )
    rew_code = resp_rew.status_code
    assert rew_code == 200
    assert resp_rew.json()["run_id"] == "run-alias-test"

    # 4. Abort run
    resp_ab = client.post(
        "/api/v1/runs/run-alias-test/abort", headers={"X-Hexaqueue-User": "bob"}
    )
    ab_code = resp_ab.status_code
    assert ab_code == 200
    assert resp_ab.json()["outcome"] == "CANCELLED"


def test_hexastack_workflow_orchestrator_integration(
    hermetic_api_client: TestClient,
) -> None:
    """Verify Hexastack's HexaqueueWorkflowOrchestratorAdapter compiled payload executes on server."""
    client = hermetic_api_client
    spec = {
        "workflow_name": "etl_pipeline",
        "version": "1.0.0",
        "description": "ETL DAG",
        "jobs": [
            {
                "id": "step_extract",
                "name": "step_extract",
                "stage": "stage_1",
                "timeout_seconds": None,
                "max_attempts": 1,
                "payload": {"data": [1]},
                "metadata": {},
            },
            {
                "id": "step_transform",
                "name": "step_transform",
                "stage": "stage_2",
                "timeout_seconds": None,
                "max_attempts": 1,
                "payload": {"ok": True},
                "metadata": {},
            },
        ],
        "dependencies": [{"parent": "step_extract", "child": "step_transform"}],
        "initial_inputs": {"run_id": "etl-001"},
    }

    # Submit via POST /api/v1/runs
    resp = client.post(
        "/api/v1/runs",
        json=spec,
        headers={"X-Hexaqueue-User": "alice"},
    )
    post_code = resp.status_code
    assert post_code == 201
    data = resp.json()
    assert data["run_id"] is not None
    assert data["total_jobs"] == 2


def test_runs_rewind_endpoint(hermetic_api_client: TestClient) -> None:
    """Verify POST /v1/runs/{run_id}/rewind resets target jobs."""
    client = hermetic_api_client
    payload = {
        "run_spec": {
            "id": "run-rewind-api",
            "name": "rewind-run",
            "tags": ["owner:alice"],
        },
        "jobs": [
            {
                "id": "job-r1",
                "run_id": "run-rewind-api",
                "name": "r1",
                "command": "echo r1",
                "tags": ["owner:alice"],
            },
            {
                "id": "job-r2",
                "run_id": "run-rewind-api",
                "name": "r2",
                "command": "echo r2",
                "tags": ["owner:alice"],
            },
        ],
        "dependencies": {"job-r2": ["job-r1"]},
    }
    client.post("/v1/runs", json=payload, headers={"X-Hexaqueue-User": "alice"})

    # Rewind job-r1
    rewind_payload = {"target_job_ids": ["job-r1"]}
    resp = client.post(
        "/v1/runs/run-rewind-api/rewind",
        json=rewind_payload,
        headers={"X-Hexaqueue-User": "alice"},
    )
    code = resp.status_code
    assert code == 200
    data = resp.json()
    assert data["run_id"] == "run-rewind-api"
    assert "job-r1" in data["rewound_job_ids"]
    assert "job-r2" in data["rewound_job_ids"]
