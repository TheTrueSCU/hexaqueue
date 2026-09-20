"""Unit tests for Hexaqueue Web Dashboard presentation router."""

import asyncio
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_dashboard.infra.app import create_dashboard_app
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.domain.models import RunSubmission
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


@pytest.fixture
def hermetic_dashboard_client() -> Generator[TestClient]:
    """Hermetic fixture providing a clean Web Dashboard TestClient."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    seed_job = JobSpec(
        id="job-dash-1",
        run_id="run-dash-seed",
        name="task-dash",
        command="echo dash",
        resources=ResourceRequirements(cpus=1, ram_mb=1024),
        tags=["owner:alice"],
    )
    run_spec = RunSpec(id="run-dash-seed", name="seed-run", tags=["owner:alice"])
    asyncio.run(
        controller.submit_run(RunSubmission(run_spec=run_spec, jobs=[seed_job]))
    )
    log_store: dict[str, list[LogChunk]] = {
        "job-dash-1": [
            LogChunk(
                job_id="job-dash-1",
                stream="stdout",
                content="Dashboard worker initialized\n",
                offset=0,
            ),
        ]
    }
    pipeline = create_hexaqueue_execution_pipeline(
        controller=controller, log_store=log_store
    )
    app = create_dashboard_app(pipeline=pipeline)
    with TestClient(app) as client:
        yield client


def test_dashboard_overview_and_telemetry(
    hermetic_dashboard_client: TestClient,
) -> None:
    """Verify cluster overview, stats, nodes, and fair-share hierarchy."""
    client = hermetic_dashboard_client

    # Overview
    overview_resp = client.get("/dashboard/overview")
    assert overview_resp.status_code == 200
    overview_data = overview_resp.json()
    assert "total_jobs" in overview_data
    assert "active_workers" in overview_data

    # Stats
    stats_resp = client.get("/dashboard/stats")
    assert stats_resp.status_code == 200
    assert "total_jobs" in stats_resp.json()

    # Nodes
    nodes_resp = client.get("/dashboard/nodes")
    assert nodes_resp.status_code == 200
    assert len(nodes_resp.json()) >= 1

    # Fair-share
    fs_resp = client.get("/dashboard/fairshare")
    assert fs_resp.status_code == 200
    assert fs_resp.json()["root"]["id"] == "root"


def test_dashboard_run_and_suite_submission(
    hermetic_dashboard_client: TestClient,
) -> None:
    """Verify run submission, suite submission, job listing, and detail views."""
    client = hermetic_dashboard_client

    # 1. Submit Run
    run_payload = {
        "run_spec": {"id": "run-dash-100", "name": "Dashboard Run"},
        "jobs": [
            {
                "id": "job-dash-2",
                "run_id": "run-dash-100",
                "name": "dash-task",
                "command": "echo hello",
                "resources": {"cpus": 1, "ram_mb": 512},
                "tags": ["owner:charlie"],
            }
        ],
        "dependencies": {},
        "user_id": "charlie",
        "elevate": False,
    }
    run_resp = client.post("/dashboard/runs/submit", json=run_payload)
    assert run_resp.status_code == 201
    assert run_resp.json()["run_id"] == "run-dash-100"

    # 2. Submit Suite
    suite_payload = {
        "suite_spec": {
            "id": "suite-dash-100",
            "name": "Suite Workload",
            "tasks": [
                {
                    "id": "task-suite-1",
                    "command": "echo suite",
                    "resources": {"cpus": 1, "ram_mb": 512},
                }
            ],
        },
        "user_id": "charlie",
        "elevate": False,
    }
    suite_resp = client.post("/dashboard/suites/submit", json=suite_payload)
    assert suite_resp.status_code == 201
    assert suite_resp.json()["run_id"] == "suite-dash-100"

    # 3. List and Get Jobs
    jobs_resp = client.get("/dashboard/jobs")
    assert jobs_resp.status_code == 200
    assert len(jobs_resp.json()) >= 1

    single_job_resp = client.get("/dashboard/jobs/job-dash-2")
    assert single_job_resp.status_code == 200
    assert single_job_resp.json()["id"] == "job-dash-2"


def test_dashboard_job_action_and_elevation(
    hermetic_dashboard_client: TestClient,
) -> None:
    """Verify least privilege and positive administrative elevation on job actions."""
    client = hermetic_dashboard_client

    # 1. Natural owner alice holds her job -> 200 OK
    alice_hold = client.post(
        "/dashboard/jobs/job-dash-1/action",
        headers={"X-Hexaqueue-User": "alice"},
        json={"action": "hold", "elevate": False},
    )
    assert alice_hold.status_code == 200
    assert alice_hold.json()["status"]["state"] == JobState.BLOCKED.value

    # 2. Cross-tenant user bob attempts to release alice's job without elevation -> 403 Forbidden
    bob_rel_forbidden = client.post(
        "/dashboard/jobs/job-dash-1/action",
        headers={"X-Hexaqueue-User": "bob"},
        json={"action": "release", "elevate": False},
    )
    assert bob_rel_forbidden.status_code == 403
    assert "Permission denied" in bob_rel_forbidden.json()["detail"]

    # 3. Cross-tenant user bob with positive elevation releases alice's job -> 200 OK
    bob_rel_elevated = client.post(
        "/dashboard/jobs/job-dash-1/action",
        headers={"X-Hexaqueue-User": "bob"},
        json={"action": "release", "elevate": True},
    )
    assert bob_rel_elevated.status_code == 200
    assert bob_rel_elevated.json()["status"]["state"] == JobState.PENDING.value

    # 4. Cancel action with elevation -> 200 OK
    admin_cancel = client.post(
        "/dashboard/jobs/job-dash-1/action",
        headers={"X-Hexaqueue-User": "bob", "X-Hexaqueue-Elevate": "true"},
        json={"action": "cancel", "elevate": False},
    )
    assert admin_cancel.status_code == 200
    assert admin_cancel.json()["status"]["state"] == JobState.DONE.value

    # 5. Invalid action -> 400 Bad Request
    invalid_resp = client.post(
        "/dashboard/jobs/job-dash-1/action",
        headers={"X-Hexaqueue-User": "alice"},
        json={"action": "reboot", "elevate": False},
    )
    assert invalid_resp.status_code == 400


def test_dashboard_explain_logs_terminal(
    hermetic_dashboard_client: TestClient,
) -> None:
    """Verify scheduling explainability, execution logs, and PTY terminal."""
    client = hermetic_dashboard_client

    # 1. Explain
    explain_resp = client.get(
        "/dashboard/jobs/job-dash-1/explain",
        headers={"X-Hexaqueue-User": "alice"},
    )
    assert explain_resp.status_code == 200
    assert explain_resp.json()["job_id"] == "job-dash-1"

    # 2. Logs
    logs_resp = client.get(
        "/dashboard/jobs/job-dash-1/logs",
        headers={"X-Hexaqueue-User": "alice"},
    )
    assert logs_resp.status_code == 200
    assert len(logs_resp.json()) == 1

    # 3. PTY Terminal
    term_resp = client.post(
        "/dashboard/jobs/job-dash-1/terminal",
        headers={"X-Hexaqueue-User": "alice"},
        json={
            "job_id": "job-dash-1",
            "session_id": "dash-term-1",
            "command": ["/bin/sh"],
        },
    )
    assert term_resp.status_code == 200
    assert term_resp.json()["session_id"] == "dash-term-1"


def test_dashboard_collateral_and_bastion_elevation(
    hermetic_dashboard_client: TestClient,
) -> None:
    """Verify collateral upload and administrative bastion elevation."""
    client = hermetic_dashboard_client

    # 1. Collateral upload
    col_resp = client.post(
        "/dashboard/collateral/upload",
        headers={"X-Hexaqueue-User": "alice"},
        json={
            "name": "data.tar.gz",
            "size_bytes": 4096,
            "checksum_sha256": "f" * 64,
        },
    )
    assert col_resp.status_code == 200
    assert col_resp.json()["filename"] == "data.tar.gz"

    # 2. Bastion SSH without elevation -> 403 Forbidden
    bastion_forbidden = client.post(
        "/dashboard/nodes/worker-01/ssh",
        headers={"X-Hexaqueue-User": "alice"},
        json={"node_id": "worker-01", "elevate": False},
    )
    assert bastion_forbidden.status_code == 403
    assert "administrative elevation" in bastion_forbidden.json()["detail"]

    # 3. Bastion SSH with positive elevation -> 200 OK
    bastion_ok = client.post(
        "/dashboard/nodes/worker-01/ssh",
        headers={"X-Hexaqueue-User": "alice"},
        json={"node_id": "worker-01", "elevate": True},
    )
    assert bastion_ok.status_code == 200
    assert bastion_ok.json()["is_active"] is True

    # 4. Cancel run
    cancel_run_resp = client.post(
        "/dashboard/runs/run-dash-seed/cancel",
        headers={"X-Hexaqueue-User": "alice"},
    )
    assert cancel_run_resp.status_code == 200
