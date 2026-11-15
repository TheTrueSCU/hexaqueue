"""Unit tests for Hexaqueue Dashboard hexastack-auth RBAC and HTTPS transport."""

from __future__ import annotations

import asyncio
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from hexastack_auth.domain.models import Identity

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_dashboard.adapters.auth import (
    SESSION_COOKIE_NAME,
    DashboardAuthManager,
    LoginRequest,
    require_roles,
)
from hexaqueue_dashboard.adapters.rbac_store import SqliteRbacPolicyAdapter
from hexaqueue_dashboard.domain.rbac import RbacPrincipal
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
    rbac_store = SqliteRbacPolicyAdapter(":memory:")
    auth_manager = DashboardAuthManager(
        jwt_secret="test-jwt-secret-key-at-least-32-bytes-long",
        rbac_store=rbac_store,
    )
    rbac_store.upsert_principal(
        RbacPrincipal(
            principal_id="rjdw",
            hashed_secret=auth_manager.hash_secret("rjdw-web-secret"),
            roles=frozenset({"admin"}),
        )
    )
    rbac_store.upsert_principal(
        RbacPrincipal(
            principal_id="hexaqueue-ci",
            hashed_secret=auth_manager.hash_secret("ci-api-secret"),
            roles=frozenset({"ci"}),
        )
    )

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


def test_login_request_redacts_secret_in_repr() -> None:
    """Verify LoginRequest SecretStr never leaks raw credentials in logs/repr."""
    req = LoginRequest(username="rjdw", password="super-secret-value")
    rendered = repr(req)
    assert "super-secret-value" not in rendered


def test_require_roles_single_any_and_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify generalized require_roles dependency for single, any, and all role modes."""
    monkeypatch.setenv("HEXAQUEUE_REQUIRE_HTTPS", "1")
    store = SqliteRbacPolicyAdapter(":memory:")
    manager = DashboardAuthManager(
        jwt_secret="test-jwt-secret-key-at-least-32-bytes-long",
        rbac_store=store,
    )
    app = FastAPI()
    app.state.auth_manager = manager

    @app.get("/any-op")
    def any_op(
        identity: Annotated[Identity, Depends(require_roles("admin", "operator"))],
    ) -> dict[str, str]:
        return {"user": identity.user_id}

    @app.get("/all-roles")
    def all_roles(
        identity: Annotated[
            Identity, Depends(require_roles("admin", "operator", match_all=True))
        ],
    ) -> dict[str, str]:
        return {"user": identity.user_id}

    op_token = manager.issue_token(
        Identity(user_id="ops-1", roles=frozenset({"operator"}), is_authenticated=True)
    )
    both_token = manager.issue_token(
        Identity(
            user_id="rjdw",
            roles=frozenset({"admin", "operator"}),
            is_authenticated=True,
        )
    )

    with TestClient(app, base_url="https://testserver") as client:
        unauth_code = client.get("/any-op").status_code
        assert unauth_code == 401

        any_ok = client.get("/any-op", headers={"Authorization": f"Bearer {op_token}"})
        assert any_ok.status_code == 200

        all_denied = client.get(
            "/all-roles", headers={"Authorization": f"Bearer {op_token}"}
        )
        assert all_denied.status_code == 403

        all_ok = client.get(
            "/all-roles", headers={"Authorization": f"Bearer {both_token}"}
        )
        assert all_ok.status_code == 200


def test_dashboard_rotate_password_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify POST /dashboard/auth/rotate-password verifies current secret and updates hash."""
    client, _ = _build_seeded_client(monkeypatch)
    with client:
        bad_rot = client.post(
            "/dashboard/auth/rotate-password",
            json={
                "username": "rjdw",
                "current_secret": "wrong-pw",
                "new_secret": "new-pw-123",
            },
            headers={"X-Forwarded-Proto": "https"},
        )
        bad_code = bad_rot.status_code
        assert bad_code == 401

        good_rot = client.post(
            "/dashboard/auth/rotate-password",
            json={
                "username": "rjdw",
                "current_secret": "rjdw-web-secret",
                "new_secret": "new-pw-123",
            },
            headers={"X-Forwarded-Proto": "https"},
        )
        good_code = good_rot.status_code
        assert good_code == 200
        assert good_rot.json() == {"status": "rotated", "principal_id": "rjdw"}

        old_login = client.post(
            "/dashboard/auth/login",
            json={"username": "rjdw", "password": "rjdw-web-secret"},
            headers={"X-Forwarded-Proto": "https"},
        )
        old_code = old_login.status_code
        assert old_code == 401

        new_login = client.post(
            "/dashboard/auth/login",
            json={"username": "rjdw", "password": "new-pw-123"},
            headers={"X-Forwarded-Proto": "https"},
        )
        new_code = new_login.status_code
        assert new_code == 200
