"""NiceGUI reactive operator console adapter for Hexaqueue Dashboard.

Notes/Architectural Intent:
    Serves as the thin composition shell for the NiceGUI operator console at
    `/dashboard/ui`, delegating individual views (login, status badge, runs DAG
    tree, jobs table, and inspection drawer) to `hexaqueue_dashboard.adapters.ui`.
"""

from __future__ import annotations

import importlib.resources
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from hexastack_auth.domain.models import Identity
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_ui.adapters.nicegui import dispatch_query, ui_page
from nicegui import app as nicegui_app
from nicegui import ui

from hexaqueue_core.domain.cqrs import (
    ClusterStatsReport,
    GetNodesQuery,
    GetQueueStatsQuery,
    ListJobsQuery,
    ListRunsQuery,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_dashboard.adapters.auth import DashboardAuthManager
from hexaqueue_dashboard.adapters.ui.jobs_table import (
    compute_filtered_kpi_counts,
    render_jobs_section,
)
from hexaqueue_dashboard.adapters.ui.login import (
    render_login_panel,
    resolve_session_identity,
)
from hexaqueue_dashboard.adapters.ui.runs_tree import render_runs_section
from hexaqueue_dashboard.adapters.ui.status import render_live_status_widget
from hexaqueue_server.domain.models import RunStatusReport
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse

_logger = logging.getLogger(__name__)


def _resolve_static_dir() -> Path | None:
    """Resolve the static asset directory using PEP 451/616 importlib.resources.

    Returns:
        Path to static asset directory if present, otherwise None.
    """
    try:
        traversable = importlib.resources.files(
            "hexaqueue_dashboard.adapters"
        ).joinpath("static")
        if traversable.is_dir():
            if isinstance(traversable, Path):
                return traversable
            candidate = Path(str(traversable))
            if candidate.is_dir():
                return candidate
    except (TypeError, FileNotFoundError, ModuleNotFoundError) as exc:
        _logger.debug(
            "Could not resolve dashboard static dir via importlib.resources: %s", exc
        )
    fallback = Path(__file__).parent / "static"
    return fallback if fallback.is_dir() else None


async def _fetch_cluster_snapshot(
    pipeline: ExecutionPipeline,
    identity: Identity,
) -> tuple[
    ClusterStatsReport,
    list[NodeTelemetryPulse],
    list[JobSpec],
    list[RunStatusReport],
    str,
]:
    """Fetch cluster stats, active nodes, jobs, runs, and a stable diff fingerprint.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.

    Returns:
        Tuple of ``(stats, nodes, jobs, runs, fingerprint)``.
    """
    is_admin = "admin" in identity.roles
    stats: ClusterStatsReport = await dispatch_query(pipeline, GetQueueStatsQuery())
    nodes: list[NodeTelemetryPulse] = await dispatch_query(pipeline, GetNodesQuery())
    jobs: list[JobSpec] = await dispatch_query(
        pipeline, ListJobsQuery(user_id=identity.user_id, elevate=is_admin)
    )
    runs: list[RunStatusReport] = await dispatch_query(
        pipeline, ListRunsQuery(user_id=identity.user_id, elevate=is_admin)
    )
    fingerprint = json.dumps(
        {
            "stats": {
                "total_jobs": stats.total_jobs,
                "pending_jobs": stats.pending_jobs,
                "running_jobs": stats.running_jobs,
                "completed_jobs": stats.completed_jobs,
                "failed_jobs": stats.failed_jobs,
            },
            "nodes": len(nodes),
            "jobs": [(j.id, str(j.state), str(j.outcome)) for j in jobs],
            "runs": [(r.run_id, str(r.state), str(r.outcome)) for r in runs],
        },
        sort_keys=True,
    )
    return stats, nodes, jobs, runs, fingerprint


async def _render_console_panel(
    pipeline: ExecutionPipeline,
    identity: Identity,
    *,
    live_status_js_url: str | None = None,
) -> None:
    """Render the authenticated Hexaqueue operator console.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
        live_status_js_url: Optional URL for the static `live_status.js` script.
    """
    roles_label = ", ".join(sorted(identity.roles))
    snapshot_box: list[
        tuple[
            ClusterStatsReport,
            list[NodeTelemetryPulse],
            list[JobSpec],
            list[RunStatusReport],
            str,
        ]
    ] = [await _fetch_cluster_snapshot(pipeline, identity)]
    filter_state: dict[str, str] = {"search": "", "status": "ALL"}
    filter_controls: dict[str, Any] = {}

    def _notify_live_badge(changed: bool) -> None:
        flag = "true" if changed else "false"
        ui.run_javascript(
            "window.dispatchEvent(new CustomEvent('hq:cluster-update', "
            f"{{detail: {{changed: {flag}}}}}))"
        )

    async def _refresh_now(*, force: bool = False) -> None:
        _, _, _, _, prev_fp = snapshot_box[0]
        next_data = await _fetch_cluster_snapshot(pipeline, identity)
        changed = force or next_data[4] != prev_fp
        if changed:
            snapshot_box[0] = next_data
            _cluster_body.refresh()
        _notify_live_badge(changed)

    async def _handle_manual_refresh() -> None:
        await _refresh_now(force=True)

    async def _handle_timer_tick() -> None:
        await _refresh_now(force=False)

    def _filter_to_run(run_id: str) -> None:
        filter_state["search"] = run_id
        search_input = filter_controls.get("search_input")
        if search_input is not None:
            search_input.value = run_id
        _cluster_body.refresh()

    def _clear_filters() -> None:
        filter_state["search"] = ""
        filter_state["status"] = "ALL"
        search_input = filter_controls.get("search_input")
        if search_input is not None:
            search_input.value = ""
        status_select = filter_controls.get("status_select")
        if status_select is not None:
            status_select.value = "ALL"
        _cluster_body.refresh()

    @ui.refreshable
    async def _cluster_body() -> None:
        stats, nodes, jobs, runs, _fp = snapshot_box[0]
        total_cnt, running_cnt, pending_cnt, is_filtered = compute_filtered_kpi_counts(
            jobs,
            search_text=filter_state.get("search", ""),
            status_filter=filter_state.get("status", "ALL"),
        )
        total_label = (
            f"Total Jobs: {total_cnt} / {stats.total_jobs}"
            if is_filtered
            else f"Total Jobs: {total_cnt}"
        )
        with ui.row().classes("w-full gap-4 mt-4"):
            with ui.card().classes("p-4"):
                ui.label(total_label).classes("font-semibold")
            with ui.card().classes("p-4"):
                ui.label(f"Running: {running_cnt}").classes("font-semibold")
            with ui.card().classes("p-4"):
                ui.label(f"Pending: {pending_cnt}").classes("font-semibold")
            with ui.card().classes("p-4"):
                ui.label(f"Active Nodes: {len(nodes)}").classes("font-semibold")

        render_runs_section(
            pipeline,
            identity,
            runs,
            jobs,
            filter_state=filter_state,
            on_mutated=_handle_manual_refresh,
            on_filter_run=_filter_to_run,
        )
        await render_jobs_section(
            pipeline,
            identity,
            jobs=jobs,
            runs=runs,
            on_mutated=_handle_manual_refresh,
            on_filter_run=_filter_to_run,
            filter_state=filter_state,
        )

    with ui.header().classes("items-center justify-between px-6"):
        ui.label("Hexaqueue Operator Console").classes("text-lg font-bold")
        with ui.row().classes("items-center gap-3"):
            render_live_status_widget(live_status_js_url)
            ui.label(f"{identity.user_id} ({roles_label})").classes("text-sm")
            ui.button(
                "Refresh",
                on_click=_handle_manual_refresh,
                icon="refresh",
            ).props('aria-label="Refresh cluster status"').tooltip("Refresh status")

            def _logout() -> None:
                nicegui_app.storage.user.pop("jwt", None)
                ui.navigate.reload()

            ui.button("Sign Out", on_click=_logout, icon="logout").props(
                'aria-label="Sign out"'
            ).tooltip("Sign out")

    with ui.row().classes("w-full items-center gap-3 mt-4"):

        def _on_search_change(ev: object) -> None:
            new_val = str(getattr(ev, "value", "") or "")
            if new_val != filter_state["search"]:
                filter_state["search"] = new_val
                _cluster_body.refresh()

        def _on_status_change(ev: object) -> None:
            new_val = str(getattr(ev, "value", "ALL") or "ALL")
            if new_val != filter_state["status"]:
                filter_state["status"] = new_val
                _cluster_body.refresh()

        filter_controls["search_input"] = (
            ui.input(
                label="Search Jobs / Runs / Workers",
                placeholder="Filter by job ID, run ID, name, or worker...",
                on_change=_on_search_change,
            )
            .props('clearable aria-label="Filter jobs by ID, run ID, name, or worker"')
            .classes("w-80")
        )
        filter_controls["status_select"] = (
            ui.select(
                options=[
                    "ALL",
                    "PENDING",
                    "RUNNING",
                    "IN_PROGRESS",
                    "HELD",
                    "COMPLETED",
                    "SUCCEEDED",
                    "FAILED",
                    "CANCELLED",
                    "BLOCKED",
                ],
                value="ALL",
                label="Status Filter",
                on_change=_on_status_change,
            )
            .props('aria-label="Filter jobs by status"')
            .classes("w-48")
        )
        ui.button(
            "Clear Filters",
            on_click=_clear_filters,
            icon="filter_alt_off",
        ).props(
            'size="sm" color="primary" aria-label="Clear search and status filters"'
        ).tooltip("Reset search and status filters")

    await _cluster_body()
    ui.timer(2.0, _handle_timer_tick)


def mount_dashboard_ui(
    app: FastAPI,
    pipeline: ExecutionPipeline,
    *,
    auth_manager: DashboardAuthManager | None = None,
    mount_path: str = "/dashboard/ui",
) -> None:
    """Mount the NiceGUI operator console onto a FastAPI application.

    Args:
        app: Target FastAPI application instance.
        pipeline: Shared CQRS ExecutionPipeline.
        auth_manager: Optional DashboardAuthManager instance.
        mount_path: URL path for the NiceGUI dashboard page.

    Notes/Architectural Intent:
        Uses `hexastack_ui.adapters.nicegui.mount_ui_app` and `ui_page` so all
        dashboard actions flow through the shared CQRS pipeline and `hexastack-auth`
        RBAC checks.
    """
    manager = (
        auth_manager
        or getattr(app.state, "auth_manager", None)
        or DashboardAuthManager()
    )
    app.state.auth_manager = manager

    static_dir = _resolve_static_dir()
    live_status_js_path = static_dir / "live_status.js" if static_dir else None
    live_status_js_url = (
        nicegui_app.add_static_file(local_file=live_status_js_path)
        if live_status_js_path is not None and live_status_js_path.is_file()
        else None
    )

    @ui_page(mount_path, title="Hexaqueue Operator Console", dark=True)
    async def _dashboard_page() -> None:
        ui.colors(primary="#1d4ed8", negative="#b91c1c")
        identity = resolve_session_identity(manager)
        if identity is None:
            render_login_panel(manager, live_status_js_url=live_status_js_url)
            return
        await _render_console_panel(
            pipeline,
            identity,
            live_status_js_url=live_status_js_url,
        )

    storage_secret = os.environ.get("HEXAQUEUE_JWT_SECRET") or secrets.token_urlsafe(32)
    ui.run_with(
        app,
        title="Hexaqueue Operator Console",
        dark=True,
        language="en-US",
        storage_secret=storage_secret,
    )


__all__ = [
    "mount_dashboard_ui",
]
