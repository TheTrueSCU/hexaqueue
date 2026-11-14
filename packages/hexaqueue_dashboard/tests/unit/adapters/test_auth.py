"""Unit tests for Hexaqueue Dashboard hexastack-auth RBAC and HTTPS transport."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_dashboard.adapters.auth import (
    SESSION_COOKIE_NAME,
    DashboardAuthManager,
)
from hexaqueue_dashboard.infra.app import create_dashboard_app
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.domain.models import RunSubmission
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


def _build_seeded_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    base_url: str = "https://testserver",
) -> tuple[TestClient, DashboardAuthManager]:
    """Create a hermetic TestClient with rjdw (admin) and hexaqueue-ci (ci) jobs."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    rjdw_job = JobSpec(
        id="job-rjdw-1",
        run_id="run-rjdw",
        name="admin-task",
        command="echo admin",
        resources=ResourceRequirements(cpus=1, ram_mb=512),
        tags=["owner:rjdw"],
    )
    ci_job = JobSpec(
        id="job-ci-1",
        run_id="run-ci",
        name="ci-task",
        command="echo ci",
        resources=ResourceRequirements(cpus=1, ram_mb=512),
        tags=["owner:hexaqueue-ci"],
    )
    asyncio.run(
        controller.submit_run(
            RunSubmission(
                run_spec=RunSpec(id="run-rjdw", name="rjdw-run", tags=["owner:rjdw"]),
                jobs=[rjdw_job],
            )
        )
    )
    asyncio.run(
        controller.submit_run(
            RunSubmission(
                run_spec=RunSpec(
                    id="run-ci", name="ci-run", tags=["owner:hexaqueue-ci"]
                ),
                jobs=[ci_job],
            )
        )
    )
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    auth_manager = DashboardAuthManager(
        jwt_secret="test-jwt-secret-key-at-least-32-bytes-long",
        admin_user="rjdw",
        ci_user="hexaqueue-ci",
    )
    auth_manager.admin_password_hash = auth_manager.hash_secret("rjdw-web-secret")
    auth_manager.ci_token_hash = auth_manager.hash_secret("ci-api-secret")

    monkeypatch.setenv("HEXAQUEUE_ALLOW_ANONYMOUS_ADMIN", "0")
    monkeypatch.setenv("HEXAQUEUE_REQUIRE_HTTPS", "1")
    app = create_dashboard_app(
        pipeline=pipeline,
        auth_manager=auth_manager,
        enable_ui=False,
    )
    return TestClient(app, base_url=base_url), auth_manager


def test_dashboard_auth_rbac_and_kill_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify rjdw can kill hexaqueue-ci jobs while hexaqueue-ci cannot kill rjdw jobs."""
    client, _ = _build_seeded_client(monkeypatch)
    with client:
        unauth_resp = client.get("/dashboard/auth/me")
        unauth_code = unauth_resp.status_code
        assert unauth_code == 401

        # Authenticate as hexaqueue-ci over Tailscale-style X-Forwarded-Proto: https
        ci_login = client.post(
            "/dashboard/auth/login",
            json={"username": "hexaqueue-ci", "password": "ci-api-secret"},
            headers={"X-Forwarded-Proto": "https"},
        )
        ci_status = ci_login.status_code
        assert ci_status == 200
        ci_cookie = ci_login.cookies.get(SESSION_COOKIE_NAME)
        assert ci_cookie is not None
        set_cookie_hdr = ci_login.headers.get("set-cookie", "")
        assert "HttpOnly" in set_cookie_hdr
        assert "Secure" in set_cookie_hdr

        # hexaqueue-ci cannot kill rjdw's job even when attempting elevate=True in body
        ci_kill_rjdw = client.post(
            "/dashboard/jobs/job-rjdw-1/action",
            json={"action": "cancel", "elevate": True},
        )
        ci_kill_rjdw_code = ci_kill_rjdw.status_code
        assert ci_kill_rjdw_code == 403

        # hexaqueue-ci can kill its own job
        ci_kill_own = client.post(
            "/dashboard/jobs/job-ci-1/action",
            json={"action": "cancel"},
        )
        ci_kill_own_code = ci_kill_own.status_code
        assert ci_kill_own_code == 200

        # Sign in as rjdw (admin)
        admin_login = client.post(
            "/dashboard/auth/login",
            json={"username": "rjdw", "password": "rjdw-web-secret"},
            headers={"X-Forwarded-Proto": "https"},
        )
        admin_status = admin_login.status_code
        assert admin_status == 200
        admin_data = admin_login.json()
        assert admin_data["user_id"] == "rjdw"
        assert admin_data["is_admin"] is True

        # rjdw can kill any job (including hexaqueue-ci's)
        admin_kill_ci = client.post(
            "/dashboard/jobs/job-ci-1/action",
            json={"action": "cancel"},
        )
        admin_kill_ci_code = admin_kill_ci.status_code
        assert admin_kill_ci_code == 200


def test_dashboard_rejects_non_https_non_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify non-loopback plaintext HTTP is rejected when HTTPS is required."""
    client, _ = _build_seeded_client(monkeypatch, base_url="http://testserver")
    with client:
        resp = client.get(
            "/dashboard/auth/me",
            headers={"X-Forwarded-For": "203.0.113.10", "X-Forwarded-Proto": "http"},
        )
        code = resp.status_code
        assert code == 403
