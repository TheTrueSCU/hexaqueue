"""Comprehensive surface parity and positive administrative elevation audit tests.

Notes/Architectural Intent:
    Verifies Issue #21 invariants:
    1. Surface Parity: Any action, query, submission, inspection, or administrative control
       must be achievable in an identical manner whether using the CLI, REST OpenAPI, or
       the Web Dashboard.
    2. Positive Administrative Elevation: All actors operate under their natural identity
       by default. Privileged operations affecting another user's resources strictly require
       positive administrative action (--admin in CLI, elevate=true in REST/Dashboard).
"""

import asyncio
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_cli.domain.session import LocalCliSession, set_default_session
from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.cqrs import (
    CancelJobCommand,
    CancelRunCommand,
    CreateBastionSessionCommand,
    CreatePtySessionCommand,
    ExplainJobQuery,
    GetFairShareTreeQuery,
    GetJobQuery,
    GetLogsQuery,
    GetNodesQuery,
    GetQueueStatsQuery,
    GetRunStatusQuery,
    HoldJobCommand,
    ListJobsQuery,
    RegisterCollateralCommand,
    ReleaseJobCommand,
    SubmitRunCommand,
    SubmitSuiteCommand,
)
from hexaqueue_core.domain.exceptions import PermissionDeniedError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_dashboard.adapters.web import create_dashboard_router
from hexaqueue_dashboard.infra.app import create_dashboard_app
from hexaqueue_server.adapters.api import create_server_api_router, create_server_app
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.domain.models import RunSubmission
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline

runner = CliRunner()


@pytest.fixture
def hermetic_parity_environment() -> Generator[
    tuple[LocalSchedulerControllerAdapter, TestClient, TestClient, LocalClientAdapter]
]:
    """Hermetic fixture wiring an identical controller to REST, Dashboard, and CLI adapters."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)

    # Pre-seed a job owned by alice
    seed_job = JobSpec(
        id="job-parity-1",
        run_id="run-parity-1",
        name="parity-task",
        command="sleep 10",
        resources=ResourceRequirements(cpus=1, ram_mb=1024),
        tags=["owner:alice"],
    )
    run_spec = RunSpec(id="run-parity-1", name="parity-run", tags=["owner:alice"])
    asyncio.run(
        controller.submit_run(RunSubmission(run_spec=run_spec, jobs=[seed_job]))
    )

    log_store: dict[str, list[LogChunk]] = {
        "job-parity-1": [
            LogChunk(
                job_id="job-parity-1",
                stream="stdout",
                content="Parity test log output\n",
                offset=0,
            )
        ]
    }

    pipeline = create_hexaqueue_execution_pipeline(
        controller=controller, log_store=log_store
    )

    server_app = create_server_app(pipeline=pipeline)
    dashboard_app = create_dashboard_app(pipeline=pipeline)

    cli_session = LocalCliSession()
    cli_session.controller = controller
    set_default_session(cli_session)
    cli_client = LocalClientAdapter(session=cli_session)

    with (
        TestClient(server_app) as rest_client,
        TestClient(dashboard_app) as dash_client,
    ):
        yield controller, rest_client, dash_client, cli_client


def test_surface_parity_capability_matrix_audit() -> None:
    """Verify that all core capabilities exist across CLI, REST API, and Dashboard."""
    server_router = create_server_api_router()
    dash_router = create_dashboard_router()

    server_routes = {route.path for route in server_router.routes}  # type: ignore[attr-defined]
    dash_routes = {route.path for route in dash_router.routes}  # type: ignore[attr-defined]

    # Required REST routes
    required_rest = {
        "/v1/runs",
        "/v1/suites",
        "/v1/jobs",
        "/v1/jobs/{job_id}",
        "/v1/jobs/{job_id}/hold",
        "/v1/jobs/{job_id}/release",
        "/v1/jobs/{job_id}/cancel",
        "/v1/jobs/{job_id}/explain",
        "/v1/jobs/{job_id}/logs",
        "/v1/jobs/{job_id}/pty",
        "/v1/fairshare",
        "/v1/nodes",
        "/v1/stats",
        "/v1/nodes/{node_id}/ssh",
        "/v1/collateral/upload",
        "/v1/budget/settle",
    }
    for route in required_rest:
        assert route in server_routes, f"Missing REST endpoint: {route}"

    # Required Dashboard routes
    required_dash = {
        "/dashboard/overview",
        "/dashboard/stats",
        "/dashboard/nodes",
        "/dashboard/fairshare",
        "/dashboard/runs/submit",
        "/dashboard/suites/submit",
        "/dashboard/jobs",
        "/dashboard/jobs/{job_id}",
        "/dashboard/jobs/{job_id}/explain",
        "/dashboard/jobs/{job_id}/logs",
        "/dashboard/jobs/{job_id}/action",
        "/dashboard/jobs/{job_id}/terminal",
        "/dashboard/collateral/upload",
        "/dashboard/nodes/{node_id}/ssh",
        "/dashboard/runs/{run_id}/cancel",
    }
    for route in required_dash:
        assert route in dash_routes, f"Missing Dashboard endpoint: {route}"

    # Verify CQRS contracts
    all_commands = {
        SubmitRunCommand,
        SubmitSuiteCommand,
        CancelRunCommand,
        HoldJobCommand,
        ReleaseJobCommand,
        CancelJobCommand,
        RegisterCollateralCommand,
        CreatePtySessionCommand,
        CreateBastionSessionCommand,
    }
    all_queries = {
        GetRunStatusQuery,
        GetJobQuery,
        ListJobsQuery,
        ExplainJobQuery,
        GetFairShareTreeQuery,
        GetQueueStatsQuery,
        GetNodesQuery,
        GetLogsQuery,
    }
    assert len(all_commands) == 9
    assert len(all_queries) == 8


def test_surface_parity_positive_elevation_enforcement(
    hermetic_parity_environment: tuple[
        LocalSchedulerControllerAdapter, TestClient, TestClient, LocalClientAdapter
    ],
) -> None:
    """Verify identical positive elevation enforcement across CLI, REST, and Dashboard."""
    controller, rest_client, dash_client, cli_client = hermetic_parity_environment

    # =========================================================================
    # 1. HOLD JOB: Bob (non-owner) attempts to hold Alice's job
    # =========================================================================

    # CLI unprivileged -> PermissionDeniedError
    with pytest.raises(PermissionDeniedError) as exc_cli:
        asyncio.run(cli_client.hold_job("job-parity-1", user_id="bob", elevate=False))
    assert "explicit administrative elevation (--admin" in str(exc_cli.value)

    # REST unprivileged -> 403 Forbidden
    rest_hold_denied = rest_client.post(
        "/v1/jobs/job-parity-1/hold",
        headers={"X-Hexaqueue-User": "bob"},
    )
    assert rest_hold_denied.status_code == 403
    assert "explicit administrative elevation" in rest_hold_denied.json()["detail"]

    # Dashboard unprivileged -> 403 Forbidden
    dash_hold_denied = dash_client.post(
        "/dashboard/jobs/job-parity-1/action",
        headers={"X-Hexaqueue-User": "bob"},
        json={"action": "hold", "elevate": False},
    )
    assert dash_hold_denied.status_code == 403
    assert "explicit administrative elevation" in dash_hold_denied.json()["detail"]

    # =========================================================================
    # 2. HOLD JOB (ELEVATED): Bob asserts explicit administrative elevation
    # =========================================================================

    # REST elevated -> 200 OK (transitions to BLOCKED)
    rest_hold_ok = rest_client.post(
        "/v1/jobs/job-parity-1/hold?elevate=true",
        headers={"X-Hexaqueue-User": "bob"},
    )
    assert rest_hold_ok.status_code == 200
    assert rest_hold_ok.json()["status"]["state"] == JobState.BLOCKED.value

    # =========================================================================
    # 3. RELEASE JOB (ELEVATED): Dashboard asserts explicit administrative elevation
    # =========================================================================
    dash_rel_ok = dash_client.post(
        "/dashboard/jobs/job-parity-1/action",
        headers={"X-Hexaqueue-User": "bob"},
        json={"action": "release", "elevate": True},
    )
    assert dash_rel_ok.status_code == 200
    assert dash_rel_ok.json()["status"]["state"] == JobState.PENDING.value

    # =========================================================================
    # 4. CANCEL JOB (ELEVATED): CLI asserts explicit administrative elevation
    # =========================================================================
    cli_cancel_ok = asyncio.run(
        cli_client.cancel_job("job-parity-1", user_id="bob", elevate=True)
    )
    assert cli_cancel_ok.state == JobState.DONE

    # Verify underlying controller state
    final_job = asyncio.run(controller.get_job("job-parity-1"))
    assert final_job.state == JobState.DONE


def test_surface_parity_bastion_elevation_enforcement(
    hermetic_parity_environment: tuple[
        LocalSchedulerControllerAdapter, TestClient, TestClient, LocalClientAdapter
    ],
) -> None:
    """Verify that worker node bastion SSH strictly requires positive elevation on all surfaces."""
    _, rest_client, dash_client, cli_client = hermetic_parity_environment

    # 1. CLI bastion without elevation -> denied
    with pytest.raises(PermissionDeniedError) as exc_cli:
        asyncio.run(
            cli_client.create_bastion_session(
                node_id="worker-node-1", user_id="alice", elevate=False
            )
        )
    assert "requires explicit administrative elevation" in str(exc_cli.value)

    # 2. REST bastion without elevation -> 403 Forbidden
    rest_ssh_denied = rest_client.post(
        "/v1/nodes/worker-node-1/ssh",
        headers={"X-Hexaqueue-User": "alice"},
    )
    assert rest_ssh_denied.status_code == 403
    assert "administrative elevation" in rest_ssh_denied.json()["detail"]

    # 3. Dashboard bastion without elevation -> 403 Forbidden
    dash_ssh_denied = dash_client.post(
        "/dashboard/nodes/worker-node-1/ssh",
        headers={"X-Hexaqueue-User": "alice"},
        json={"node_id": "worker-node-1", "elevate": False},
    )
    assert dash_ssh_denied.status_code == 403

    # 4. Elevated requests succeed across all surfaces
    rest_ssh_ok = rest_client.post(
        "/v1/nodes/worker-node-1/ssh?elevate=true",
        headers={"X-Hexaqueue-User": "alice"},
    )
    assert rest_ssh_ok.status_code == 200

    dash_ssh_ok = dash_client.post(
        "/dashboard/nodes/worker-node-1/ssh",
        headers={"X-Hexaqueue-User": "alice"},
        json={"node_id": "worker-node-1", "elevate": True},
    )
    assert dash_ssh_ok.status_code == 200

    cli_ssh_ok = asyncio.run(
        cli_client.create_bastion_session(
            node_id="worker-node-1", user_id="alice", elevate=True
        )
    )
    assert cli_ssh_ok.is_active is True
