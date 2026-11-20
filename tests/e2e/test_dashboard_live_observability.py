"""End-to-end Playwright tests for live worker telemetry, topology updates, and log streaming.

Notes/Architectural Intent:
    Exercises the full burst-worker observability path across FastAPI worker-pool
    endpoints (`/worker/register`, `/worker/{id}/heartbeat`, `/worker/{id}/logs/{job_id}`),
    `SliceLeaseCoordinator`, CQRS `handle_get_nodes` / `handle_get_logs`, and the
    NiceGUI operator console in a real Chromium browser.
"""

from __future__ import annotations

import html
import json
from collections.abc import Generator
from typing import Any

import httpx
import pytest
from hexastack_fastapi.testing.server import EphemeralServer
from playwright.async_api import Page, async_playwright, expect

AXE_CORE_CDN_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js"

LIVE_OBSERVABILITY_APP_CODE = """
import asyncio
import os
import uvicorn
from hexastack_auth.adapters.password import Pbkdf2PasswordHasher
from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_dashboard.adapters.auth import DashboardAuthManager
from hexaqueue_dashboard.adapters.nicegui_ui import mount_dashboard_ui
from hexaqueue_dashboard.adapters.rbac_store import InMemoryRbacPolicyAdapter
from hexaqueue_dashboard.infra.app import create_dashboard_app
from hexaqueue_server.adapters.api.worker_pool import create_worker_pool_router
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.domain.lease_coordinator import SliceLeaseCoordinator
from hexaqueue_server.domain.models import RunSubmission
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline

os.environ["HEXAQUEUE_REQUIRE_HTTPS"] = "0"
os.environ["HEXAQUEUE_ALLOW_ANONYMOUS_ADMIN"] = "0"
os.environ.pop("HEXAQUEUE_JOIN_TOKEN", None)

queue = InMemoryJobQueueAdapter()
controller = LocalSchedulerControllerAdapter(queue=queue)
log_store = dict()
coordinator = SliceLeaseCoordinator(controller=controller, log_store=log_store)
controller._lease_coordinator = coordinator

asyncio.run(
    controller.submit_run(
        RunSubmission(
            run_spec=RunSpec(id="obs-run-1", name="live-observability-run"),
            jobs=[
                JobSpec(
                    id="obs-job-1",
                    run_id="obs-run-1",
                    name="live_obs_job",
                    command="echo streaming",
                )
            ],
        )
    )
)
pipeline = create_hexaqueue_execution_pipeline(
    controller=controller,
    log_store=log_store,
)
auth_manager = DashboardAuthManager(
    jwt_secret="e2e-live-obs-test-secret-key-0123456789abcdef",
    rbac_store=InMemoryRbacPolicyAdapter(),
    admin_user="e2e-admin",
    admin_password_hash=Pbkdf2PasswordHasher().hash_password("e2e-secret-pass"),
)
app = create_dashboard_app(
    pipeline=pipeline,
    auth_manager=auth_manager,
    enable_ui=False,
)
app.include_router(create_worker_pool_router(coordinator=coordinator))
mount_dashboard_ui(app, pipeline, auth_manager=app.state.auth_manager)
uvicorn.run(app, host="127.0.0.1", port={port}, log_level="warning")
"""


@pytest.fixture(scope="module")
def live_obs_server() -> Generator[str]:
    """Spawn an ephemeral dashboard + worker-pool server on a free local port."""
    server = EphemeralServer(app_factory_code=LIVE_OBSERVABILITY_APP_CODE)
    url = server.start(ready_path="/dashboard/ui", timeout=30.0)
    yield url
    server.stop()


async def _run_axe_scan(page: Page) -> list[dict[str, Any]]:
    """Inject axe-core and return WCAG 2.1 AA violations for the current DOM."""
    has_axe = await page.evaluate("() => typeof window.axe !== 'undefined'")
    if not has_axe:
        await page.add_script_tag(url=AXE_CORE_CDN_URL)
        await page.wait_for_function("() => typeof window.axe !== 'undefined'")

    results_json = await page.evaluate(
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
@pytest.mark.asyncio
async def test_dashboard_live_worker_telemetry_topology_and_logs(
    live_obs_server: str,
) -> None:
    """Verify live worker heartbeats, dynamic topology updates, and log streaming E2E.

    Args:
        live_obs_server: Base URL of the running ephemeral dashboard + worker server.
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        try:
            await _verify_live_observability_flow(page, live_obs_server)
        finally:
            await browser.close()


async def _verify_live_observability_flow(page: Page, base_url: str) -> None:
    """Drive login, worker registration, heartbeat updates, topology change, and log tail."""
    await page.goto(f"{base_url}/dashboard/ui")
    await expect(page.get_by_text("Hexaqueue Operator Sign In")).to_be_visible()

    await page.get_by_label("Username").fill("e2e-admin")
    await page.get_by_label("Web Password / CI Token").fill("e2e-secret-pass")
    await page.get_by_role("button", name="Sign in to Hexaqueue Dashboard").click()
    await expect(page.get_by_text("Hexaqueue Operator Console")).to_be_visible()

    # 1. Navigate to Active Nodes & Topology
    await page.get_by_role(
        "button", name="Switch to Active Nodes and Topology view"
    ).click()
    await expect(page.get_by_text("Cluster Topology", exact=True)).to_be_visible()

    topology_locator = page.get_by_role(
        "img", name="Hexaqueue cluster topology diagram"
    )
    await expect(topology_locator).to_be_visible()

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        # 2. Register burst worker 1 and push live host telemetry via heartbeat
        reg1 = await client.post(
            "/worker/register",
            json={
                "worker_id": "e2e-burst-w1",
                "hostname": "burst-w1.local",
                "ocpus": 4,
                "memory_mb": 8192,
            },
        )
        reg1_status = reg1.status_code
        assert reg1_status == 201

        hb1 = await client.post(
            "/worker/e2e-burst-w1/heartbeat",
            json={
                "active_lease_ids": [],
                "cpu_utilization_pct": 37.5,
                "memory_used_mb": 2048,
                "memory_total_mb": 8192,
                "scratch_used_mb": 512,
                "scratch_total_mb": 10240,
            },
        )
        hb1_status = hb1.status_code
        assert hb1_status == 200

        # Active Nodes table updates automatically on the 2s live timer
        await expect(
            page.get_by_role("cell", name="e2e-burst-w1", exact=True)
        ).to_be_visible(timeout=10000)
        await expect(page.get_by_role("cell", name="37.5%", exact=True)).to_be_visible(
            timeout=10000
        )

        # Topology diagram reflects e2e-burst-w1 without baking volatile CPU metrics
        topo_html_1 = html.unescape(await topology_locator.inner_html())
        assert "e2e-burst-w1" in topo_html_1
        assert "CPU 37%" not in topo_html_1

        # 3. Push updated CPU telemetry; table updates in place
        hb2 = await client.post(
            "/worker/e2e-burst-w1/heartbeat",
            json={
                "active_lease_ids": [],
                "cpu_utilization_pct": 64.0,
                "memory_used_mb": 3072,
                "memory_total_mb": 8192,
                "scratch_used_mb": 640,
                "scratch_total_mb": 10240,
            },
        )
        hb2_status = hb2.status_code
        assert hb2_status == 200
        await expect(page.get_by_role("cell", name="64.0%", exact=True)).to_be_visible(
            timeout=10000
        )

        # 4. Register burst worker 2; topology diagram dynamically refreshes
        reg2 = await client.post(
            "/worker/register",
            json={
                "worker_id": "e2e-burst-w2",
                "hostname": "burst-w2.local",
                "ocpus": 2,
                "memory_mb": 4096,
            },
        )
        reg2_status = reg2.status_code
        assert reg2_status == 201

        await expect(
            page.get_by_role("cell", name="e2e-burst-w2", exact=True)
        ).to_be_visible(timeout=10000)
        topo_html_2 = html.unescape(await topology_locator.inner_html())
        assert "e2e-burst-w1" in topo_html_2
        assert "e2e-burst-w2" in topo_html_2

        # 5. WCAG 2.1 AA audit on populated Active Nodes & Topology view
        nodes_violations = await _run_axe_scan(page)
        critical_nodes = [
            v for v in nodes_violations if v.get("impact") in ("critical", "serious")
        ]
        crit_count = len(critical_nodes)
        assert crit_count == 0, (
            f"Accessibility violations on live Active Nodes view: {critical_nodes}"
        )

        # 6. Stream incremental live logs from burst worker and verify in Job Drawer
        log_resp = await client.post(
            "/worker/e2e-burst-w1/logs/obs-job-1",
            json=[
                {
                    "job_id": "obs-job-1",
                    "stream": "stdout",
                    "content": "STAGE 1: bootstrapping live burst worker",
                    "offset": 0,
                },
                {
                    "job_id": "obs-job-1",
                    "stream": "stdout",
                    "content": "STAGE 2: streaming telemetry OK",
                    "offset": 1,
                },
            ],
        )
        log_status = log_resp.status_code
        assert log_status == 200

    await page.get_by_role("button", name="Switch to Jobs view").click()
    await expect(page.get_by_text("live_obs_job")).to_be_visible(timeout=10000)

    await page.get_by_role("button", name="Inspect job obs-job-1").click()
    await expect(page.get_by_text("Execution Logs")).to_be_visible(timeout=10000)
    await expect(
        page.get_by_text("STAGE 1: bootstrapping live burst worker")
    ).to_be_visible(timeout=10000)
    await expect(page.get_by_text("STAGE 2: streaming telemetry OK")).to_be_visible(
        timeout=10000
    )
