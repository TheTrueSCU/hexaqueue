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

    # Submit Run with user_id="default" and X-Hexaqueue-User header
    run_default_user_payload = {
        "run_spec": {"id": "run-dash-101", "name": "Default User Run"},
        "jobs": [
            {
                "id": "job-dash-3",
                "run_id": "run-dash-101",
                "name": "dash-task-3",
                "command": "echo default user",
                "resources": {"cpus": 1, "ram_mb": 512},
                "tags": ["owner:alice"],
            }
        ],
        "dependencies": {},
        "user_id": "default",
        "elevate": True,
    }
    run_resp2 = client.post(
        "/dashboard/runs/submit",
        json=run_default_user_payload,
        headers={"X-Hexaqueue-User": "alice"},
    )
    assert run_resp2.status_code == 201
    assert run_resp2.json()["run_id"] == "run-dash-101"

    # Submit Suite with user_id="default" and X-Hexaqueue-User header
    suite_default_payload = {
        "suite_spec": {
            "id": "suite-dash-101",
            "name": "Suite Workload Default",
            "tasks": [
                {
                    "id": "task-suite-2",
                    "command": "echo suite default",
                    "resources": {"cpus": 1, "ram_mb": 512},
                }
            ],
        },
        "user_id": "default",
        "elevate": True,
    }
    suite_resp2 = client.post(
        "/dashboard/suites/submit",
        json=suite_default_payload,
        headers={"X-Hexaqueue-User": "alice"},
    )
    assert suite_resp2.status_code == 201
    assert suite_resp2.json()["run_id"] == "suite-dash-101"

    # 3. List and Get Jobs
    jobs_resp = client.get("/dashboard/jobs")
    assert jobs_resp.status_code == 200
    assert len(jobs_resp.json()) >= 1

    single_job_resp = client.get("/dashboard/jobs/job-dash-2")
    assert single_job_resp.status_code == 200
    assert single_job_resp.json()["id"] == "job-dash-2"

    job3_resp = client.get("/dashboard/jobs/job-dash-3")
    assert job3_resp.status_code == 200
    assert "owner:alice" in job3_resp.json()["tags"]


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

    term_default_session = client.post(
        "/dashboard/jobs/job-dash-1/terminal",
        headers={"X-Hexaqueue-User": "alice"},
        json={
            "job_id": "job-dash-1",
            "session_id": "dash-term-custom",
            "command": ["/bin/sh"],
            "user_id": "default",
        },
    )
    assert term_default_session.status_code == 200
    assert term_default_session.json()["session_id"] == "dash-term-custom"


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
    assert bastion_ok.json()["session_id"].startswith("bastion-")

    # Bastion SSH with custom session_id
    bastion_custom = client.post(
        "/dashboard/nodes/worker-01/ssh",
        headers={"X-Hexaqueue-User": "alice"},
        json={
            "node_id": "worker-01",
            "session_id": "custom-bastion-42",
            "elevate": True,
        },
    )
    assert bastion_custom.status_code == 200
    assert bastion_custom.json()["session_id"] == "custom-bastion-42"

    # Bastion SSH with header elevation and payload elevate=False
    bastion_header_elevate = client.post(
        "/dashboard/nodes/worker-01/ssh",
        headers={"X-Hexaqueue-User": "alice", "X-Hexaqueue-Elevate": "true"},
        json={"node_id": "worker-01", "elevate": False},
    )
    assert bastion_header_elevate.status_code == 200

    # 4. Cancel run
    cancel_run_resp = client.post(
        "/dashboard/runs/run-dash-seed/cancel",
        headers={"X-Hexaqueue-User": "alice"},
    )
    assert cancel_run_resp.status_code == 200


def test_get_auth_context_unit() -> None:
    """Verify get_auth_context resolution of user and elevation states."""
    from hexaqueue_dashboard.adapters.web import get_auth_context

    # 1. Defaults
    assert get_auth_context() == ("default", False)
    assert get_auth_context(None, False, False) == ("default", False)

    # 2. User identity
    assert get_auth_context(x_hexaqueue_user="alice") == ("alice", False)
    assert get_auth_context(x_hexaqueue_user="") == ("default", False)

    # 3. Header elevation
    assert get_auth_context(x_hexaqueue_elevate=True, elevate=False) == (
        "default",
        True,
    )

    # 4. Query elevation
    assert get_auth_context(x_hexaqueue_elevate=False, elevate=True) == (
        "default",
        True,
    )

    # 5. Both elevation
    assert get_auth_context(x_hexaqueue_elevate=True, elevate=True) == (
        "default",
        True,
    )

    # 6. User and elevation combined
    assert get_auth_context(x_hexaqueue_user="charlie", x_hexaqueue_elevate=True) == (
        "charlie",
        True,
    )
    assert get_auth_context(x_hexaqueue_user="charlie", elevate=True) == (
        "charlie",
        True,
    )


def test_dashboard_command_elevation_and_user_mapping() -> None:
    """Verify endpoint dispatch mapping for user identity and elevation.

    Notes/Architectural Intent:
        Guarantees that user identity fallback to authenticated principal
        and elevation boolean composition (OR logic) behave correctly across
        run submissions, suite submissions, and PTY terminal activations.
    """
    from unittest.mock import MagicMock

    from fastapi.routing import APIRoute

    from hexaqueue_core.domain.cqrs import (
        CreatePtySessionCommand,
        SubmitRunCommand,
        SubmitSuiteCommand,
    )
    from hexaqueue_core.domain.job import JobSpec
    from hexaqueue_core.domain.resources import ResourceRequirements
    from hexaqueue_core.domain.run import RunSpec
    from hexaqueue_core.domain.suite import SuiteSpec, TaskSpec
    from hexaqueue_dashboard.adapters.web import create_dashboard_router

    router = create_dashboard_router()
    routes = {r.path: r.endpoint for r in router.routes if isinstance(r, APIRoute)}
    submit_run = routes["/dashboard/runs/submit"]
    submit_suite = routes["/dashboard/suites/submit"]
    create_terminal = routes["/dashboard/jobs/{job_id}/terminal"]

    mock_pip = MagicMock()
    job = JobSpec(
        id="j1",
        run_id="r1",
        name="j1",
        command="echo",
        resources=ResourceRequirements(cpus=1, ram_mb=512),
    )

    # 1. submit_run: user_id="default" falls back to auth user; user_id="bob" is preserved
    cmd_default = SubmitRunCommand(
        run_spec=RunSpec(id="r1", name="r1"),
        jobs=[job],
        user_id="default",
        elevate=False,
    )
    submit_run(cmd=cmd_default, pip=mock_pip, auth=("alice", False))
    dispatched = mock_pip.execute.call_args[0][0]
    assert dispatched.user_id == "alice"
    assert dispatched.elevate is False

    cmd_explicit = SubmitRunCommand(
        run_spec=RunSpec(id="r1", name="r1"),
        jobs=[job],
        user_id="bob",
        elevate=False,
    )
    submit_run(cmd=cmd_explicit, pip=mock_pip, auth=("alice", False))
    dispatched = mock_pip.execute.call_args[0][0]
    assert dispatched.user_id == "bob"
    assert dispatched.elevate is False

    # 2. submit_run: elevation OR composition
    cmd_elevated = SubmitRunCommand(
        run_spec=RunSpec(id="r1", name="r1"),
        jobs=[job],
        user_id="alice",
        elevate=True,
    )
    submit_run(cmd=cmd_elevated, pip=mock_pip, auth=("alice", False))
    dispatched = mock_pip.execute.call_args[0][0]
    assert dispatched.elevate is True

    submit_run(cmd=cmd_default, pip=mock_pip, auth=("alice", True))
    dispatched = mock_pip.execute.call_args[0][0]
    assert dispatched.elevate is True

    # 3. submit_suite: user_id fallback and elevation OR composition
    suite_cmd_default = SubmitSuiteCommand(
        suite_spec=SuiteSpec(
            id="s1",
            name="s1",
            tasks=[
                TaskSpec(
                    id="t1",
                    command="echo",
                    resources=ResourceRequirements(cpus=1, ram_mb=512),
                )
            ],
        ),
        user_id="default",
        elevate=False,
    )
    submit_suite(cmd=suite_cmd_default, pip=mock_pip, auth=("alice", False))
    dispatched = mock_pip.execute.call_args[0][0]
    assert dispatched.user_id == "alice"
    assert dispatched.elevate is False

    suite_cmd_explicit = SubmitSuiteCommand(
        suite_spec=SuiteSpec(
            id="s1",
            name="s1",
            tasks=[
                TaskSpec(
                    id="t1",
                    command="echo",
                    resources=ResourceRequirements(cpus=1, ram_mb=512),
                )
            ],
        ),
        user_id="bob",
        elevate=False,
    )
    submit_suite(cmd=suite_cmd_explicit, pip=mock_pip, auth=("alice", False))
    dispatched = mock_pip.execute.call_args[0][0]
    assert dispatched.user_id == "bob"
    assert dispatched.elevate is False

    suite_cmd_elevated = SubmitSuiteCommand(
        suite_spec=SuiteSpec(
            id="s1",
            name="s1",
            tasks=[
                TaskSpec(
                    id="t1",
                    command="echo",
                    resources=ResourceRequirements(cpus=1, ram_mb=512),
                )
            ],
        ),
        user_id="alice",
        elevate=True,
    )
    submit_suite(cmd=suite_cmd_elevated, pip=mock_pip, auth=("alice", False))
    dispatched = mock_pip.execute.call_args[0][0]
    assert dispatched.elevate is True

    submit_suite(cmd=suite_cmd_default, pip=mock_pip, auth=("alice", True))
    dispatched = mock_pip.execute.call_args[0][0]
    assert dispatched.elevate is True

    # 4. create_terminal: elevation OR composition
    pty_cmd = CreatePtySessionCommand(
        job_id="j1",
        session_id="pty-test",
        command=["/bin/sh"],
        user_id="default",
        elevate=False,
    )
    create_terminal(job_id="j1", cmd=pty_cmd, pip=mock_pip, auth=("alice", False))
    dispatched = mock_pip.execute.call_args[0][0]
    assert dispatched.elevate is False

    create_terminal(job_id="j1", cmd=pty_cmd, pip=mock_pip, auth=("alice", True))
    dispatched = mock_pip.execute.call_args[0][0]
    assert dispatched.elevate is True

    pty_cmd_elevated = CreatePtySessionCommand(
        job_id="j1",
        session_id="pty-test",
        command=["/bin/sh"],
        user_id="default",
        elevate=True,
    )
    create_terminal(
        job_id="j1", cmd=pty_cmd_elevated, pip=mock_pip, auth=("alice", False)
    )
    dispatched = mock_pip.execute.call_args[0][0]
    assert dispatched.elevate is True
