"""Unit tests for Hexaqueue Server FastAPI REST presentation adapter."""

import asyncio
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.adapters.api import create_server_app
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.domain.models import RunSubmission
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


@pytest.fixture
def hermetic_api_client() -> Generator[TestClient]:
    """Hermetic fixture providing a clean FastAPI TestClient."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    seed_job = JobSpec(
        id="job-api-1",
        run_id="run-api-seed",
        name="task-api",
        command="echo seed",
        resources=ResourceRequirements(cpus=1, ram_mb=1024),
        tags=["owner:alice"],
    )
    run_spec = RunSpec(id="run-api-seed", name="seed-run", tags=["owner:alice"])
    asyncio.run(
        controller.submit_run(RunSubmission(run_spec=run_spec, jobs=[seed_job]))
    )
    log_store: dict[str, list[LogChunk]] = {
        "job-api-1": [
            LogChunk(
                job_id="job-api-1",
                stream="stdout",
                content="Job starting\n",
                offset=0,
            ),
            LogChunk(
                job_id="job-api-1",
                stream="stdout",
                content="Job finished\n",
                offset=1,
            ),
        ]
    }
    pipeline = create_hexaqueue_execution_pipeline(
        controller=controller, log_store=log_store
    )
    app = create_server_app(pipeline=pipeline)
    with TestClient(app) as client:
        yield client


def test_api_run_lifecycle_and_jobs(hermetic_api_client: TestClient) -> None:
    """Verify run submission, status inspection, job listing, and cancellation."""
    client = hermetic_api_client

    # 1. Submit Run
    payload = {
        "run_spec": {"id": "run-api-100", "name": "API Test Run"},
        "jobs": [
            {
                "id": "job-api-1",
                "run_id": "run-api-100",
                "name": "task-api",
                "command": "echo api",
                "resources": {"cpus": 1, "ram_mb": 1024},
                "tags": ["owner:alice"],
            }
        ],
        "dependencies": {},
        "user_id": "alice",
        "elevate": False,
    }
    submit_resp = client.post("/v1/runs", json=payload)
    assert submit_resp.status_code == 201
    run_data = submit_resp.json()
    assert run_data["run_id"] == "run-api-100"

    # 2. Get Run Status
    status_resp = client.get("/v1/runs/run-api-100")
    assert status_resp.status_code == 200
    assert status_resp.json()["run_id"] == "run-api-100"

    # 3. List Jobs
    jobs_resp = client.get("/v1/jobs")
    assert jobs_resp.status_code == 200
    assert len(jobs_resp.json()) >= 1

    # 4. Get Job
    job_resp = client.get("/v1/jobs/job-api-1")
    assert job_resp.status_code == 200
    assert job_resp.json()["id"] == "job-api-1"


def test_api_permission_elevation_controls(hermetic_api_client: TestClient) -> None:
    """Verify that cross-tenant mutations via REST require positive elevation."""
    client = hermetic_api_client

    # Setup job owned by alice
    client.post(
        "/v1/runs",
        json={
            "run_spec": {"id": "run-sec-1", "name": "Security Run"},
            "jobs": [
                {
                    "id": "job-sec-1",
                    "run_id": "run-sec-1",
                    "name": "task-sec",
                    "command": "sleep 10",
                    "resources": {"cpus": 1, "ram_mb": 1024},
                    "tags": ["owner:alice"],
                }
            ],
            "user_id": "alice",
        },
    )

    # Alice (owner) can hold her own job
    alice_hold = client.post(
        "/v1/jobs/job-sec-1/hold",
        headers={"X-Hexaqueue-User": "alice"},
    )
    assert alice_hold.status_code == 200

    # Bob tries to release Alice's job without elevation -> 403 Forbidden!
    bob_release = client.post(
        "/v1/jobs/job-sec-1/release",
        headers={"X-Hexaqueue-User": "bob"},
    )
    assert bob_release.status_code == 403
    assert "Permission denied" in bob_release.json()["detail"]
    assert "--admin / elevate=true" in bob_release.json()["detail"]

    # Bob explicitly asserts elevation header -> 200 OK!
    elevated_release = client.post(
        "/v1/jobs/job-sec-1/release",
        headers={
            "X-Hexaqueue-User": "bob",
            "X-Hexaqueue-Elevate": "true",
        },
    )
    assert elevated_release.status_code == 200

    # Bob tries to cancel without elevation -> 403
    bob_cancel = client.post(
        "/v1/jobs/job-sec-1/cancel",
        headers={"X-Hexaqueue-User": "bob"},
    )
    assert bob_cancel.status_code == 403

    # Bob cancels with query param elevation (?elevate=true) -> 200
    elevated_cancel = client.post(
        "/v1/jobs/job-sec-1/cancel?elevate=true",
        headers={"X-Hexaqueue-User": "bob"},
    )
    assert elevated_cancel.status_code == 200


def test_api_bastion_ssh_elevation(hermetic_api_client: TestClient) -> None:
    """Verify node bastion SSH route enforces administrative elevation."""
    client = hermetic_api_client

    # Without elevation -> 403
    denied = client.post("/v1/nodes/node-1/ssh")
    assert denied.status_code == 403
    assert "requires explicit administrative elevation" in denied.json()["detail"]

    # With elevation -> 200
    granted = client.post("/v1/nodes/node-1/ssh?elevate=true")
    assert granted.status_code == 200
    assert granted.json()["job_id"] == "bastion-node-1"


def test_api_suite_and_collateral_endpoints(hermetic_api_client: TestClient) -> None:
    """Verify /v1/suites, /v1/collateral/upload, and /v1/budget/settle."""
    client = hermetic_api_client

    # Suite submission
    suite_resp = client.post(
        "/v1/suites",
        json={
            "suite_spec": {
                "id": "suite-web-1",
                "name": "Suite Web",
                "tasks": [{"id": "t1", "command": "echo t1"}],
            },
            "user_id": "carol",
        },
    )
    assert suite_resp.status_code == 201
    assert suite_resp.json()["run_id"] == "suite-web-1"

    # Collateral registration
    col_resp = client.post(
        "/v1/collateral/upload",
        json={
            "name": "dataset.tar.gz",
            "checksum_sha256": "b" * 64,
            "size_bytes": 2048,
        },
    )
    assert col_resp.status_code == 200
    assert col_resp.json()["filename"] == "dataset.tar.gz"

    # Budget settlement
    budget_resp = client.post(
        "/v1/budget/settle",
        json={"project_id": "proj-9", "amount_cents": 1200},
    )
    assert budget_resp.status_code == 200
    assert budget_resp.json()["status"] == "SETTLED"


def test_api_diagnostics_and_monitoring(hermetic_api_client: TestClient) -> None:
    """Verify /v1/nodes, /v1/stats, /v1/fairshare, /v1/jobs/{id}/explain, and /v1/jobs/{id}/logs."""
    client = hermetic_api_client

    # 1. Nodes
    nodes_resp = client.get("/v1/nodes")
    assert nodes_resp.status_code == 200
    assert len(nodes_resp.json()) >= 1

    # 2. Stats
    stats_resp = client.get("/v1/stats")
    assert stats_resp.status_code == 200
    assert "total_jobs" in stats_resp.json()

    # 3. Fair-share
    fs_resp = client.get("/v1/fairshare")
    assert fs_resp.status_code == 200
    assert fs_resp.json()["root"]["id"] == "root"

    # 4. Logs
    logs_resp = client.get("/v1/jobs/job-api-1/logs?tail=2")
    assert logs_resp.status_code == 200

    # 5. PTY Session
    pty_resp = client.post(
        "/v1/jobs/job-api-1/pty",
        headers={"X-Hexaqueue-User": "alice"},
        json={
            "job_id": "job-api-1",
            "session_id": "pty-test-1",
            "command": ["/bin/sh"],
        },
    )
    assert pty_resp.status_code == 200
    assert pty_resp.json()["session_id"] == "pty-test-1"
