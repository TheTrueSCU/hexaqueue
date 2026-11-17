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
from hexaqueue_dashboard.adapters.ui.nodes_view import render_nodes_section
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


def _render_kpi_cards(
    cards: list[tuple[str, str, Any]],
) -> None:
    """Render clickable summary KPI cards for the operator console.

    Args:
        cards: Sequence of ``(label_text, aria_label, click_handler)`` tuples.

    Notes/Architectural Intent:
        Extracts KPI card rendering from `_render_console_panel` to avoid
        repetitive card markup and keep cognitive complexity low.
    """
    with ui.row().classes("w-full gap-4 mt-4"):
        for label_text, aria_label, on_click in cards:
            with (
                ui.card()
                .classes("p-4 cursor-pointer hover:ring-2 hover:ring-blue-500")
                .props(f'role="button" tabindex="0" aria-label="{aria_label}"')
                .on("click", on_click)
            ):
                ui.label(label_text).classes("font-semibold")


async def _render_cluster_body_content(
    pipeline: ExecutionPipeline,
    identity: Identity,
    snapshot: tuple[
        ClusterStatsReport,
        list[NodeTelemetryPulse],
        list[JobSpec],
        list[RunStatusReport],
        str,
    ],
    filter_state: dict[str, str],
    view_state: dict[str, str],
    expanded_nodes: set[str],
    drawer_host: Any,
    *,
    on_switch_view: Any,
    on_mutated: Any,
    on_filter_run: Any,
) -> None:
    """Render KPI cards, view tabs, and active tab content for the console body.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
        snapshot: Current cluster snapshot tuple.
        filter_state: Mutable filter state mapping.
        view_state: Mutable active tab state mapping.
        expanded_nodes: Mutable set persisting expanded Runs & DAG tree keys.
        drawer_host: Persistent NiceGUI container outside refreshable blocks.
        on_switch_view: Callback to switch active tab and optional status filter.
        on_mutated: Async callback invoked after lifecycle mutations.
        on_filter_run: Callback to filter the jobs table to a run ID.

    Notes/Architectural Intent:
        Extracted from `_render_console_panel` to keep the refreshable body
        modular and well below the cognitive complexity threshold.
    """
    stats, nodes, jobs, runs, _fp = snapshot
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
    _render_kpi_cards(
        [
            (
                total_label,
                "Show all jobs",
                lambda: on_switch_view("jobs", status_filter="ALL"),
            ),
            (
                f"Running: {running_cnt}",
                "Filter to running jobs",
                lambda: on_switch_view("jobs", status_filter="RUNNING"),
            ),
            (
                f"Pending: {pending_cnt}",
                "Filter to pending jobs",
                lambda: on_switch_view("jobs", status_filter="PENDING"),
            ),
            (
                f"Active Nodes: {len(nodes)}",
                "View active nodes and cluster topology",
                lambda: on_switch_view("nodes"),
            ),
        ]
    )

    with ui.row().classes("w-full items-center gap-2 mt-4"):
        tab = view_state["tab"]
        ui.button(
            "Jobs",
            on_click=lambda: on_switch_view("jobs"),
            icon="list_alt",
            color="primary" if tab == "jobs" else "grey-8",
        ).props('size="sm" aria-label="Switch to Jobs view"')
        ui.button(
            "Runs & DAG",
            on_click=lambda: on_switch_view("runs"),
            icon="account_tree",
            color="primary" if tab == "runs" else "grey-8",
        ).props('size="sm" aria-label="Switch to Runs and DAG view"')
        ui.button(
            "Active Nodes & Topology",
            on_click=lambda: on_switch_view("nodes"),
            icon="hub",
            color="primary" if tab == "nodes" else "grey-8",
        ).props('size="sm" aria-label="Switch to Active Nodes and Topology view"')

    if tab == "nodes":
        render_nodes_section(nodes, jobs)
        return

    if tab == "runs":
        render_runs_section(
            pipeline,
            identity,
            runs,
            jobs,
            filter_state=filter_state,
            expanded_nodes=expanded_nodes,
            on_mutated=on_mutated,
            on_filter_run=on_filter_run,
            drawer_host=drawer_host,
        )
        return

    await render_jobs_section(
        pipeline,
        identity,
        jobs=jobs,
        runs=runs,
        on_mutated=on_mutated,
        on_filter_run=on_filter_run,
        filter_state=filter_state,
        drawer_host=drawer_host,
    )


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
    view_state: dict[str, str] = {"tab": "jobs"}
    expanded_nodes: set[str] = set()
    drawer_host = ui.column().classes("w-0 h-0")

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

    def _sync_filter_visibility() -> None:
        filter_row = filter_controls.get("filter_row")
        if filter_row is not None:
            filter_row.set_visibility(view_state["tab"] in ("jobs", "runs"))

    def _filter_to_run(run_id: str) -> None:
        view_state["tab"] = "jobs"
        _sync_filter_visibility()
        filter_state["search"] = run_id
        search_input = filter_controls.get("search_input")
        if search_input is not None:
            search_input.value = run_id
        _cluster_body.refresh()

    def _switch_view(tab: str, *, status_filter: str | None = None) -> None:
        view_state["tab"] = tab
        _sync_filter_visibility()
        if status_filter is not None:
            filter_state["status"] = status_filter
            status_select = filter_controls.get("status_select")
            if status_select is not None:
                status_select.value = status_filter
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
        await _render_cluster_body_content(
            pipeline,
            identity,
            snapshot_box[0],
            filter_state,
            view_state,
            expanded_nodes,
            drawer_host,
            on_switch_view=_switch_view,
            on_mutated=_handle_manual_refresh,
            on_filter_run=_filter_to_run,
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

    filter_row = ui.row().classes("w-full items-center gap-3 mt-4")
    filter_controls["filter_row"] = filter_row
    with filter_row:

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
