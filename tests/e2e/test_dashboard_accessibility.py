"""Playwright + axe-core WCAG 2.1 AA accessibility tests for Hexaqueue Dashboard.

Notes/Architectural Intent:
    Validates that the NiceGUI operator login card and authenticated operator
    console at `/dashboard/ui` satisfy WCAG 2.1 AA standards with zero
    critical or serious axe-core violations.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

import pytest
from hexastack_fastapi.testing.server import EphemeralServer
from playwright.sync_api import Page, expect

AXE_CORE_CDN_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js"

DASHBOARD_E2E_APP_CODE = """
import asyncio
import os
import uvicorn
from hexastack_auth.adapters.password import Pbkdf2PasswordHasher
from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_dashboard.adapters.auth import DashboardAuthManager
from hexaqueue_dashboard.adapters.rbac_store import InMemoryRbacPolicyAdapter
from hexaqueue_dashboard.infra.app import create_dashboard_app
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.domain.models import RunSubmission
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline

os.environ["HEXAQUEUE_REQUIRE_HTTPS"] = "0"
os.environ["HEXAQUEUE_ALLOW_ANONYMOUS_ADMIN"] = "0"

queue = InMemoryJobQueueAdapter()
controller = LocalSchedulerControllerAdapter(queue=queue)
asyncio.run(
    controller.submit_run(
        RunSubmission(
            run_spec=RunSpec(id="a11y-run-1", name="a11y-audit-run"),
            jobs=[
                JobSpec(
                    id="a11y-job-1",
                    run_id="a11y-run-1",
                    name="wcag_audit_job",
                    command="echo ok",
                )
            ],
        )
    )
)
pipeline = create_hexaqueue_execution_pipeline(controller=controller)
auth_manager = DashboardAuthManager(
    jwt_secret="e2e-a11y-test-secret-key-0123456789abcdef",
    rbac_store=InMemoryRbacPolicyAdapter(),
    admin_user="e2e-admin",
    admin_password_hash=Pbkdf2PasswordHasher().hash_password("e2e-secret-pass"),
)
app = create_dashboard_app(
    pipeline=pipeline,
    auth_manager=auth_manager,
    enable_ui=True,
)
uvicorn.run(app, host="127.0.0.1", port={port}, log_level="warning")
"""


@pytest.fixture(scope="module")
def dashboard_server() -> Generator[str]:
    """Spawn an ephemeral Hexaqueue Dashboard FastAPI + NiceGUI server."""
    server = EphemeralServer(app_factory_code=DASHBOARD_E2E_APP_CODE)
    url = server.start(ready_path="/dashboard/ui", timeout=30.0)
    yield f"{url}/dashboard/ui"
    server.stop()


def run_axe_scan(page: Page) -> list[dict[str, Any]]:
    """Inject axe-core and execute a WCAG 2.1 AA audit against the current page.

    Args:
        page: Active Playwright Page instance.

    Returns:
        List of axe-core violation dictionaries.
    """
    has_axe = page.evaluate("() => typeof window.axe !== 'undefined'")
    if not has_axe:
        page.add_script_tag(url=AXE_CORE_CDN_URL)
        page.wait_for_function("() => typeof window.axe !== 'undefined'")

    results_json = page.evaluate(
        """async () => {
            const res = await window.axe.run(document, {
                runOnly: {
                    type: 'tag',
                    values: ['wcag2a', 'wcag2aa', 'wcag21aa']
                },
                rules: {
                    'aria-progressbar-name': { enabled: false }
                }
            });
            return JSON.stringify(res.violations || []);
        }"""
    )
    return json.loads(results_json)


@pytest.mark.e2e
def test_dashboard_ui_wcag_accessibility(
    dashboard_server: str,
    page: Page,
) -> None:
    """Verify Hexaqueue Dashboard login and console views pass WCAG 2.1 AA audits.

    Args:
        dashboard_server: Base URL to the running `/dashboard/ui` endpoint.
        page: Playwright browser page fixture.
    """
    page.goto(dashboard_server)
    expect(page.get_by_text("Hexaqueue Operator Sign In")).to_be_visible()

    # 1. Audit unauthenticated login card
    login_violations = run_axe_scan(page)
    critical_login = [
        v for v in login_violations if v.get("impact") in ("critical", "serious")
    ]
    crit_login_count = len(critical_login)
    assert crit_login_count == 0, (
        f"Accessibility violations on login screen: {critical_login}"
    )

    # 2. Authenticate via the NiceGUI login form and audit operator console
    page.get_by_label("Username").fill("e2e-admin")
    page.get_by_label("Web Password / CI Token").fill("e2e-secret-pass")
    page.get_by_role("button", name="Sign in to Hexaqueue Dashboard").click()

    expect(page.get_by_text("Hexaqueue Operator Console")).to_be_visible()
    expect(page.locator("#hq-live-badge")).to_be_visible()
    expect(page.locator("#hq-live-text")).to_contain_text("Connected")
    expect(page.get_by_text("wcag_audit_job")).to_be_visible()

    console_violations = run_axe_scan(page)
    critical_console = [
        v for v in console_violations if v.get("impact") in ("critical", "serious")
    ]
    crit_console_count = len(critical_console)
    assert crit_console_count == 0, (
        f"Accessibility violations on operator console: {critical_console}"
    )

    # 2b. Switch to Runs & DAG view and audit under WCAG 2.1 AA
    page.get_by_role("button", name="Switch to Runs and DAG view").click()
    expect(page.get_by_text("Runs & DAG Tree")).to_be_visible()

    runs_violations = run_axe_scan(page)
    critical_runs = [
        v for v in runs_violations if v.get("impact") in ("critical", "serious")
    ]
    crit_runs_count = len(critical_runs)
    assert crit_runs_count == 0, (
        f"Accessibility violations on Runs & DAG view: {critical_runs}"
    )

    # 2c. Switch to Active Nodes & Topology view and audit under WCAG 2.1 AA
    page.get_by_role("button", name="Switch to Active Nodes and Topology view").click()
    expect(page.get_by_text("Cluster Topology", exact=True)).to_be_visible()
    expect(
        page.get_by_role("img", name="Hexaqueue cluster topology diagram")
    ).to_be_visible()

    nodes_violations = run_axe_scan(page)
    critical_nodes = [
        v for v in nodes_violations if v.get("impact") in ("critical", "serious")
    ]
    crit_nodes_count = len(critical_nodes)
    assert crit_nodes_count == 0, (
        f"Accessibility violations on Active Nodes & Topology view: {critical_nodes}"
    )

    page.get_by_role("button", name="Switch to Jobs view").click()
    expect(page.get_by_text("wcag_audit_job")).to_be_visible()

    # 3. Open the Job Inspection Drawer and audit under WCAG 2.1 AA
    page.get_by_role("button", name="Inspect job a11y-job-1").click()
    page.mouse.move(0, 0)
    page.wait_for_timeout(350)
    expect(page.get_by_text("Scheduler Explainability")).to_be_visible()
    expect(page.get_by_text("Execution Logs")).to_be_visible()

    drawer_violations = run_axe_scan(page)
    critical_drawer = [
        v for v in drawer_violations if v.get("impact") in ("critical", "serious")
    ]
    crit_drawer_count = len(critical_drawer)
    assert crit_drawer_count == 0, (
        f"Accessibility violations in inspection drawer: {critical_drawer}"
    )
