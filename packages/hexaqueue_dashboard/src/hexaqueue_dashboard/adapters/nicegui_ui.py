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
from hexaqueue_dashboard.adapters.ui.fairshare_view import render_fairshare_section
from hexaqueue_dashboard.adapters.ui.history_view import render_history_section
from hexaqueue_dashboard.adapters.ui.inspection_drawer import refresh_active_drawer
from hexaqueue_dashboard.adapters.ui.jobs_table import (
    compute_filtered_kpi_counts,
    render_jobs_section,
)
from hexaqueue_dashboard.adapters.ui.login import (
    open_change_password_dialog,
    render_login_panel,
    resolve_session_identity,
)
from hexaqueue_dashboard.adapters.ui.logs_view import render_live_logs_page
from hexaqueue_dashboard.adapters.ui.nodes_view import (
    build_node_rows,
    record_node_metrics_samples,
    render_nodes_section,
)
from hexaqueue_dashboard.adapters.ui.runs_tree import render_runs_section
from hexaqueue_dashboard.adapters.ui.state import ConsoleUIState, DrawerUIState
from hexaqueue_dashboard.adapters.ui.status import render_live_status_widget
from hexaqueue_server.domain.models import RunStatusReport
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse

_logger = logging.getLogger(__name__)

JOB_STATUS_FILTER_OPTIONS: dict[str, str] = {
    "ALL": "All Statuses",
    "ACTIVE": "Active (Non-Terminal)",
    "PENDING": "  \u2022 Pending",
    "SUBMITTED": "  \u2022 Submitted",
    "PROVISIONING": "  \u2022 Provisioning",
    "RUNNING": "  \u2022 Running",
    "CLEANUP": "  \u2022 Cleanup",
    "HELD": "  \u2022 Held",
    "BLOCKED": "  \u2022 Blocked",
    "TERMINAL": "Inactive (Terminal)",
    "COMPLETED": "  \u2022 Completed",
    "FAILED": "  \u2022 Failed",
    "CANCELLED": "  \u2022 Cancelled",
}
RUN_STATUS_FILTER_OPTIONS: dict[str, str] = {
    "ALL": "All Statuses",
    "ACTIVE": "Active (Non-Terminal)",
    "PENDING": "  \u2022 Pending",
    "IN_PROGRESS": "  \u2022 In Progress",
    "RUNNING": "  \u2022 Running",
    "TERMINAL": "Inactive (Terminal)",
    "COMPLETED": "  \u2022 Completed",
    "SUCCEEDED": "  \u2022 Succeeded",
    "FAILED": "  \u2022 Failed",
    "CANCELLED": "  \u2022 Cancelled",
}


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
    *,
    elevate_admin: bool | None = None,
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
        elevate_admin: Optional view-role override bounded by ``identity.roles``.

    Returns:
        Tuple of ``(stats, nodes, jobs, runs, fingerprint)``.
    """
    is_admin = (
        ("admin" in identity.roles)
        if elevate_admin is None
        else (elevate_admin and "admin" in identity.roles)
    )
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
            "kpi": {
                "total_jobs": stats.total_jobs,
                "pending_jobs": stats.pending_jobs,
                "running_jobs": stats.running_jobs,
                "completed_jobs": stats.completed_jobs,
                "failed_jobs": stats.failed_jobs,
                "node_count": len(nodes),
            },
            "nodes": [
                (
                    n.worker_id,
                    n.active_jobs,
                    round(n.cpu_utilization_pct, 1),
                    n.memory_used_mb,
                    round(n.load_average[0], 2),
                )
                for n in nodes
            ],
            "node_ts": [n.timestamp.isoformat() for n in nodes],
            "jobs_runs": {
                "jobs": [
                    (
                        j.id,
                        str(j.state),
                        str(j.outcome),
                        j.assigned_worker_id,
                        str(j.updated_at),
                    )
                    for j in jobs
                ],
                "runs": [
                    (
                        r.run_id,
                        str(r.state),
                        str(r.outcome),
                        r.completed_jobs,
                        r.running_jobs,
                        r.failed_jobs,
                    )
                    for r in runs
                ],
            },
        },
        sort_keys=True,
    )
    return stats, nodes, jobs, runs, fingerprint


def _try_update_nodes_table_in_place(
    ui_state: ConsoleUIState,
    nodes: list[Any],
    jobs: list[JobSpec],
) -> bool:
    """Update the active nodes table rows in place without tearing down the tab."""
    table = ui_state.node_table_ref.get("table")
    prev_workers = ui_state.node_table_ref.get("workers")
    next_workers = tuple(sorted(n.worker_id for n in nodes))
    if table is None or not nodes or prev_workers != next_workers:
        return False
    record_node_metrics_samples(ui_state.node_metrics_history, nodes)
    ui_state.node_table_ref["nodes_by_id"] = {n.worker_id: n for n in nodes}
    ui_state.node_table_ref["jobs"] = jobs
    table.rows = build_node_rows(nodes, jobs)
    table.update()
    return True


def _apply_body_refresh(
    ui_state: ConsoleUIState,
    next_data: tuple[Any, list[Any], list[JobSpec], list[Any], str],
    cluster_body: Any,
    *,
    force: bool,
) -> None:
    """Refresh cluster body, updating the active nodes table in place when possible."""
    if (
        not force
        and ui_state.tab == "nodes"
        and _try_update_nodes_table_in_place(ui_state, next_data[1], next_data[2])
    ):
        return
    cluster_body.refresh()


def _selective_refresh_needed(
    tab: str,
    prev_fp: str,
    next_fp: str,
    *,
    force: bool,
) -> tuple[bool, bool, bool]:
    """Determine (any_changed, refresh_kpi, refresh_body) for selective SSE updates.

    Args:
        tab: Active console tab identifier.
        prev_fp: Previous JSON snapshot fingerprint.
        next_fp: Next JSON snapshot fingerprint.
        force: Whether manual/forced refresh was requested.

    Returns:
        Tuple of ``(any_changed, refresh_kpi, refresh_body)``.

    Notes/Architectural Intent:
        Prevents background node heartbeats from re-rendering the Jobs table or
        DAG tree, and keeps History Explorer steady while browsing pages.
    """
    any_changed = force or next_fp != prev_fp
    if force:
        return True, True, True
    if not any_changed:
        return False, False, False
    prev_parts = json.loads(prev_fp)
    next_parts = json.loads(next_fp)
    refresh_kpi = next_parts.get("kpi") != prev_parts.get("kpi")
    if tab in ("jobs", "runs"):
        refresh_body = next_parts.get("jobs_runs") != prev_parts.get("jobs_runs")
    elif tab == "nodes":
        refresh_body = next_parts.get("nodes") != prev_parts.get(
            "nodes"
        ) or next_parts.get("node_ts") != prev_parts.get("node_ts")
    elif tab == "fairshare":
        refresh_body = next_parts.get("jobs_runs") != prev_parts.get(
            "jobs_runs"
        ) or next_parts.get("nodes") != prev_parts.get("nodes")
    else:
        refresh_body = False
    any_changed = (
        next_parts.get("kpi") != prev_parts.get("kpi")
        or next_parts.get("nodes") != prev_parts.get("nodes")
        or next_parts.get("jobs_runs") != prev_parts.get("jobs_runs")
        or (tab == "nodes" and next_parts.get("node_ts") != prev_parts.get("node_ts"))
    )
    return any_changed, refresh_kpi, refresh_body


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


def _resolve_is_admin_view(identity: Identity, active_role: str) -> bool:
    """Return True only when the operator holds ``admin`` and is viewing as admin."""
    return active_role == "admin" and "admin" in identity.roles


def _apply_role_switch(
    identity: Identity,
    ui_state: ConsoleUIState,
    new_role: str,
) -> None:
    """Update active view role and reset admin-only tabs when stepping down."""
    ui_state.active_role = new_role
    if not _resolve_is_admin_view(identity, new_role) and ui_state.tab in (
        "nodes",
        "fairshare",
    ):
        ui_state.tab = "jobs"
    _sync_filter_controls(ui_state)


def _render_tab_fieldset(
    legend_label: str, buttons: list[tuple[str, str, str, str, Any]]
) -> None:
    """Render a native `<fieldset>` + `<legend>` tab group container."""
    with ui.element("fieldset").classes(
        "border border-slate-700 rounded px-3 pb-2 pt-1 flex flex-wrap items-center gap-2"
    ):
        with ui.element("legend").classes(
            "px-2 text-xs font-semibold uppercase tracking-wider text-slate-300"
        ):
            ui.label(legend_label)
        for label, icon, color, aria_label, on_click in buttons:
            ui.button(label, on_click=on_click, icon=icon, color=color).props(
                f'size="sm" aria-label="{aria_label}"'
            )


def _render_kpi_and_tabs(
    snapshot: tuple[
        ClusterStatsReport,
        list[NodeTelemetryPulse],
        list[JobSpec],
        list[RunStatusReport],
        str,
    ],
    ui_state: ConsoleUIState,
    on_switch_view: Any,
    *,
    is_admin_view: bool = True,
) -> None:
    """Render summary KPI cards and role-grouped view tabs above the filter bar.

    Args:
        snapshot: Current cluster snapshot tuple.
        ui_state: Unified ConsoleUIState holding active tab and filters.
        on_switch_view: Callback to switch active tab and optional status filter.
        is_admin_view: Whether admin-only KPIs and tab group are visible.

    Notes/Architectural Intent:
        Rendered in its own refreshable slot above the persistent filter row so
        tab-scoped filters appear visually below the tabs without losing focus,
        with `<fieldset>`/`<legend>` containers separating User and Admin tabs.
    """
    stats, nodes, jobs, _runs, _fp = snapshot
    total_cnt, running_cnt, pending_cnt, is_filtered = compute_filtered_kpi_counts(
        jobs,
        search_text=ui_state.filters.search,
        status_filter=ui_state.filters.status,
    )
    total_label = (
        f"Total Jobs: {total_cnt} / {stats.total_jobs}"
        if is_filtered
        else f"Total Jobs: {total_cnt}"
    )
    kpi_cards: list[tuple[str, str, Any]] = [
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
    ]
    if is_admin_view:
        kpi_cards.append(
            (
                f"Active Nodes: {len(nodes)}",
                "View active nodes and cluster topology",
                lambda: on_switch_view("nodes"),
            )
        )
    _render_kpi_cards(kpi_cards)

    with ui.row().classes("w-full items-stretch flex-wrap gap-3 mt-4"):
        tab = ui_state.tab
        _render_tab_fieldset(
            "User",
            [
                (
                    "Jobs",
                    "list_alt",
                    "primary" if tab == "jobs" else "grey-8",
                    "Switch to Jobs view",
                    lambda: on_switch_view("jobs"),
                ),
                (
                    "Runs & DAG",
                    "account_tree",
                    "primary" if tab == "runs" else "grey-8",
                    "Switch to Runs and DAG view",
                    lambda: on_switch_view("runs"),
                ),
                (
                    "History Explorer",
                    "history",
                    "primary" if tab == "history" else "grey-8",
                    "Switch to History Explorer view",
                    lambda: on_switch_view("history"),
                ),
            ],
        )
        if is_admin_view:
            _render_tab_fieldset(
                "Admin",
                [
                    (
                        "Active Nodes & Topology",
                        "hub",
                        "primary" if tab == "nodes" else "grey-8",
                        "Switch to Active Nodes and Topology view",
                        lambda: on_switch_view("nodes"),
                    ),
                    (
                        "Fair-Share & Quotas",
                        "pie_chart",
                        "primary" if tab == "fairshare" else "grey-8",
                        "Switch to Fair-Share and Quotas view",
                        lambda: on_switch_view("fairshare"),
                    ),
                ],
            )

    if tab == "jobs":
        ui.label("Jobs").classes("text-lg font-semibold mt-4")
    elif tab == "runs":
        ui.label("Runs & DAG Tree").classes("text-lg font-semibold mt-4")


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
    ui_state: ConsoleUIState,
    *,
    on_mutated: Any,
    on_filter_run: Any,
    on_refresh: Any,
) -> None:
    """Render the active tab body below the tab-scoped filter bar.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
        snapshot: Current cluster snapshot tuple.
        ui_state: Unified ConsoleUIState holding tab, filters, and drawer state.
        on_mutated: Async callback invoked after lifecycle mutations.
        on_filter_run: Callback to filter the jobs table to a run ID.
        on_refresh: Callback to refresh console views.

    Notes/Architectural Intent:
        Extracted from `_render_console_panel` to keep the refreshable body
        modular and well below the cognitive complexity threshold.
    """
    _stats, nodes, jobs, runs, _fp = snapshot
    record_node_metrics_samples(ui_state.node_metrics_history, nodes)
    is_admin_view = _resolve_is_admin_view(identity, ui_state.active_role)
    if not is_admin_view and ui_state.tab in ("nodes", "fairshare"):
        ui_state.tab = "jobs"
    tab = ui_state.tab

    if tab == "nodes" and is_admin_view:
        render_nodes_section(
            nodes,
            jobs,
            pipeline=pipeline,
            identity=identity,
            drawer_state=ui_state.drawer,
            metrics_history=ui_state.node_metrics_history,
            node_table_ref=ui_state.node_table_ref,
        )
        return
    ui_state.node_table_ref.clear()

    if tab == "fairshare" and is_admin_view:
        await render_fairshare_section(pipeline, identity, nodes, _stats)
        return

    if tab == "history":
        render_history_section(
            pipeline,
            identity,
            runs,
            jobs,
            ui_state.history,
            ui_state.drawer,
            on_mutated=on_mutated,
            on_filter_run=on_filter_run,
            on_refresh=on_refresh,
        )
        return

    if tab == "runs":
        render_runs_section(
            pipeline,
            identity,
            runs,
            jobs,
            on_mutated=on_mutated,
            on_filter_run=on_filter_run,
            on_refresh=on_refresh,
            show_heading=False,
            filters=ui_state.filters,
            tree_state=ui_state.runs_tree,
            drawer_state=ui_state.drawer,
        )
        return

    await render_jobs_section(
        pipeline,
        identity,
        jobs=jobs,
        runs=runs,
        on_mutated=on_mutated,
        on_filter_run=on_filter_run,
        on_refresh=on_refresh,
        show_heading=False,
        filters=ui_state.filters,
        table_state=ui_state.jobs_table,
        drawer_state=ui_state.drawer,
    )


def _sync_filter_controls(ui_state: ConsoleUIState) -> None:
    """Sync filter bar visibility and valid status options with the active tab.

    Args:
        ui_state: Unified ConsoleUIState holding tab and FilterUIState.

    Notes/Architectural Intent:
        Extracted from `_render_console_panel` to keep cognitive complexity
        low while updating tab-specific status options without recreating
        input widgets.
    """
    tab = ui_state.tab
    filter_row = ui_state.filters.controls.get("filter_row")
    if filter_row is not None:
        filter_row.set_visibility(tab in ("jobs", "runs"))
    status_select = ui_state.filters.controls.get("status_select")
    if status_select is not None and tab in ("jobs", "runs"):
        valid_opts = (
            RUN_STATUS_FILTER_OPTIONS if tab == "runs" else JOB_STATUS_FILTER_OPTIONS
        )
        status_select.options = valid_opts
        if ui_state.filters.status not in valid_opts:
            ui_state.filters.status = "ALL"
            status_select.value = "ALL"
        if hasattr(status_select, "update"):
            status_select.update()


def _render_console_header(
    identity: Identity,
    roles_label: str,
    live_status_js_url: str | None,
    auth_manager: DashboardAuthManager | None,
    on_refresh: Any,
    *,
    active_role: str = "user",
    on_role_change: Any = None,
) -> None:
    """Render top navigation header with live badge, role switcher, refresh, password rotation, and sign-out."""
    with ui.header().classes("items-center justify-between px-6"):
        ui.label("Hexaqueue Operator Console").classes("text-lg font-bold")
        with ui.row().classes("items-center gap-3"):
            render_live_status_widget(live_status_js_url)
            if len(identity.roles) > 1 and on_role_change is not None:
                ui.select(
                    options=sorted(identity.roles),
                    value=active_role,
                    label="Viewing as",
                    on_change=lambda ev: on_role_change(
                        str(getattr(ev, "value", active_role) or active_role)
                    ),
                ).props(
                    'dense outlined dark options-dense bg-color="grey-10" '
                    'label-color="white" color="white" '
                    'aria-label="Select active view role"'
                ).classes("w-36")
            ui.label(f"{identity.user_id} ({roles_label})").classes("text-sm")
            ui.button(
                "Refresh",
                on_click=on_refresh,
                icon="refresh",
            ).props('aria-label="Refresh cluster status"').tooltip("Refresh status")
            if auth_manager is not None:
                ui.button(
                    "Change Password",
                    on_click=lambda: open_change_password_dialog(
                        auth_manager, identity
                    ),
                    icon="key",
                ).props('aria-label="Change password"').tooltip("Rotate password")

            def _logout() -> None:
                nicegui_app.storage.user.pop("jwt", None)
                ui.navigate.reload()

            ui.button("Sign Out", on_click=_logout, icon="logout").props(
                'aria-label="Sign out"'
            ).tooltip("Sign out")


def _render_filter_bar(
    ui_state: ConsoleUIState,
    on_refresh_views: Any,
    on_clear_filters: Any,
) -> None:
    """Render persistent search, status filter, and clear-filters controls."""
    filter_row = ui.row().classes("w-full items-center gap-3 mt-4")
    ui_state.filters.controls["filter_row"] = filter_row
    with filter_row:

        def _on_search_change(ev: object) -> None:
            new_val = str(getattr(ev, "value", "") or "")
            if new_val != ui_state.filters.search:
                ui_state.filters.search = new_val
                on_refresh_views()

        def _on_status_change(ev: object) -> None:
            new_val = str(getattr(ev, "value", "ALL") or "ALL")
            if new_val != ui_state.filters.status:
                ui_state.filters.status = new_val
                on_refresh_views()

        ui_state.filters.controls["search_input"] = (
            ui.input(
                label="Search Jobs / Runs / Workers",
                placeholder="Filter by job ID, run ID, name, or worker...",
                on_change=_on_search_change,
            )
            .props('clearable aria-label="Filter jobs by ID, run ID, name, or worker"')
            .classes("w-80")
        )
        ui_state.filters.controls["status_select"] = (
            ui.select(
                options=JOB_STATUS_FILTER_OPTIONS,
                value="ALL",
                label="Status Filter",
                on_change=_on_status_change,
            )
            .props('aria-label="Filter jobs by status"')
            .classes("w-48")
        )
        ui.button(
            "Clear Filters",
            on_click=on_clear_filters,
            icon="filter_alt_off",
        ).props(
            'size="sm" color="primary" aria-label="Clear search and status filters"'
        ).tooltip("Reset search and status filters")


async def _render_console_panel(
    pipeline: ExecutionPipeline,
    identity: Identity,
    *,
    auth_manager: DashboardAuthManager | None = None,
    live_status_js_url: str | None = None,
) -> None:
    """Render the authenticated Hexaqueue operator console.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
        auth_manager: Optional DashboardAuthManager for password rotation.
        live_status_js_url: Optional URL for the static `live_status.js` script.
    """
    roles_label = ", ".join(sorted(identity.roles))
    default_role = "admin" if "admin" in identity.roles else "user"
    drawer_host = ui.column().classes("w-0 h-0")
    ui_state = ConsoleUIState(
        active_role=default_role,
        drawer=DrawerUIState(host=drawer_host),
    )
    snapshot_box: list[
        tuple[
            ClusterStatsReport,
            list[NodeTelemetryPulse],
            list[JobSpec],
            list[RunStatusReport],
            str,
        ]
    ] = [
        await _fetch_cluster_snapshot(
            pipeline,
            identity,
            elevate_admin=_resolve_is_admin_view(identity, ui_state.active_role),
        )
    ]

    def _notify_live_badge(changed: bool) -> None:
        flag = "true" if changed else "false"
        ui.run_javascript(
            "window.dispatchEvent(new CustomEvent('hq:cluster-update', "
            f"{{detail: {{changed: {flag}}}}}))"
        )

    def _refresh_views() -> None:
        _kpi_and_tabs.refresh()
        _cluster_body.refresh()

    async def _refresh_now(*, force: bool = False) -> None:
        _, _, _, _, prev_fp = snapshot_box[0]
        next_data = await _fetch_cluster_snapshot(
            pipeline,
            identity,
            elevate_admin=_resolve_is_admin_view(identity, ui_state.active_role),
        )
        any_changed, refresh_kpi, refresh_body = _selective_refresh_needed(
            ui_state.tab, prev_fp, next_data[4], force=force
        )
        if any_changed:
            snapshot_box[0] = next_data
            if refresh_kpi:
                _kpi_and_tabs.refresh()
            if refresh_body:
                _apply_body_refresh(ui_state, next_data, _cluster_body, force=force)
            await refresh_active_drawer(
                pipeline,
                identity,
                ui_state.drawer,
                next_data[2],
                next_data[3],
                on_mutated=_handle_manual_refresh,
                on_filter_run=_filter_to_run,
            )
        _notify_live_badge(any_changed)

    async def _handle_manual_refresh() -> None:
        await _refresh_now(force=True)

    async def _handle_timer_tick() -> None:
        await _refresh_now(force=False)

    def _sync_filter_visibility() -> None:
        _sync_filter_controls(ui_state)

    def _filter_to_run(run_id: str) -> None:
        ui_state.tab = "jobs"
        _sync_filter_visibility()
        ui_state.filters.search = run_id
        search_input = ui_state.filters.controls.get("search_input")
        if search_input is not None:
            search_input.value = run_id
        _refresh_views()

    def _switch_view(tab: str, *, status_filter: str | None = None) -> None:
        ui_state.tab = tab
        _sync_filter_visibility()
        if status_filter is not None:
            ui_state.filters.status = status_filter
            status_select = ui_state.filters.controls.get("status_select")
            if status_select is not None:
                status_select.value = status_filter
        _refresh_views()

    def _clear_filters() -> None:
        ui_state.filters.search = ""
        ui_state.filters.status = "ALL"
        search_input = ui_state.filters.controls.get("search_input")
        if search_input is not None:
            search_input.value = ""
        status_select = ui_state.filters.controls.get("status_select")
        if status_select is not None:
            status_select.value = "ALL"
        _refresh_views()

    @ui.refreshable
    def _kpi_and_tabs() -> None:
        _render_kpi_and_tabs(
            snapshot_box[0],
            ui_state,
            _switch_view,
            is_admin_view=_resolve_is_admin_view(identity, ui_state.active_role),
        )

    @ui.refreshable
    async def _cluster_body() -> None:
        await _render_cluster_body_content(
            pipeline,
            identity,
            snapshot_box[0],
            ui_state,
            on_mutated=_handle_manual_refresh,
            on_filter_run=_filter_to_run,
            on_refresh=_refresh_views,
        )

    async def _on_role_change(new_role: str) -> None:
        _apply_role_switch(identity, ui_state, new_role)
        await _refresh_now(force=True)
        _refresh_views()

    _render_console_header(
        identity,
        roles_label,
        live_status_js_url,
        auth_manager,
        _handle_manual_refresh,
        active_role=ui_state.active_role,
        on_role_change=_on_role_change,
    )

    _kpi_and_tabs()

    _render_filter_bar(ui_state, _refresh_views, _clear_filters)

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
            auth_manager=manager,
            live_status_js_url=live_status_js_url,
        )

    logs_mount_path = f"{mount_path.rstrip('/')}/logs/{{job_id}}"

    @ui_page(logs_mount_path, title="Hexaqueue Live Logs", dark=True)
    async def _job_logs_page(job_id: str) -> None:
        ui.colors(primary="#1d4ed8", negative="#b91c1c")
        identity = resolve_session_identity(manager)
        if identity is None:
            render_login_panel(manager, live_status_js_url=live_status_js_url)
            return
        await render_live_logs_page(
            pipeline,
            identity,
            job_id,
            back_url=mount_path,
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
