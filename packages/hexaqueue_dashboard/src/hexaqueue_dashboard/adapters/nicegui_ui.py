"""NiceGUI reactive operator console adapter for Hexaqueue Dashboard.

Notes/Architectural Intent:
    Builds on `hexastack-ui` (`mount_ui_app`, `ui_page`, `dispatch_command`,
    `dispatch_query`) and `hexastack-auth` (`DashboardAuthManager`) to provide
    an authenticated operator console at `/dashboard/ui` over HTTPS (Tailscale
    Serve) or SSH tunnels.
"""

from __future__ import annotations

import importlib.resources
import json
import logging
import os
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI
from hexastack_auth.domain.models import Identity
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_ui.adapters.nicegui import (
    dispatch_command,
    dispatch_query,
    ui_page,
)
from nicegui import app as nicegui_app
from nicegui import ui

from hexaqueue_core.domain.cqrs import (
    CancelJobCommand,
    CancelRunCommand,
    ClusterStatsReport,
    GetNodesQuery,
    GetQueueStatsQuery,
    HoldJobCommand,
    ListJobsQuery,
    ReleaseJobCommand,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState
from hexaqueue_dashboard.adapters.auth import DashboardAuthManager
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


def _resolve_session_identity(auth_manager: DashboardAuthManager) -> Identity | None:
    """Resolve authenticated Identity from NiceGUI per-user session storage.

    Args:
        auth_manager: DashboardAuthManager used to verify stored JWT.

    Returns:
        Verified Identity if present and valid, otherwise None.
    """
    token = nicegui_app.storage.user.get("jwt")
    if not token:
        return None
    try:
        return auth_manager.verify_token(str(token))
    except Exception:
        nicegui_app.storage.user.pop("jwt", None)
        return None


def _render_login_panel(auth_manager: DashboardAuthManager) -> None:
    """Render the NiceGUI login card for `rjdw` / `hexaqueue-ci` web credentials.

    Args:
        auth_manager: DashboardAuthManager validating credentials.
    """
    with ui.card().classes("w-full max-w-md mx-auto mt-12 p-6"):
        ui.label("Hexaqueue Operator Sign In").classes("text-xl font-bold mb-2")
        username = ui.input("Username", placeholder="rjdw").classes("w-full")
        password = ui.input(
            "Web Password / CI Token", password=True, password_toggle_button=True
        ).classes("w-full")
        error_label = ui.label("").classes("text-red-500 text-sm")

        def _handle_login() -> None:
            try:
                identity = auth_manager.authenticate_user(
                    username.value or "", password.value or ""
                )
                nicegui_app.storage.user["jwt"] = auth_manager.issue_token(identity)
                ui.navigate.reload()
            except Exception:
                error_label.text = "Invalid username or credential."

        ui.button("Sign In", on_click=_handle_login, icon="login").props(
            'aria-label="Sign in to Hexaqueue Dashboard"'
        ).tooltip("Authenticate with Hexaqueue web credentials")


_STATUS_BADGE_COLORS: dict[str, str] = {
    "RUNNING": "#1d4ed8",
    "CLEANUP": "#1d4ed8",
    "PENDING": "#92400e",
    "SUBMITTED": "#92400e",
    "PROVISIONING": "#92400e",
    "HELD": "#6b21a8",
    "COMPLETED": "#15803d",
    "FAILED": "#b91c1c",
    "TIMED_OUT": "#b91c1c",
    "BLOCKED": "#b91c1c",
    "CANCELLED": "#374151",
}

_TERMINAL_DISPLAY_STATES = frozenset({"COMPLETED", "FAILED", "TIMED_OUT", "CANCELLED"})

_JOB_TABLE_COLUMNS: list[dict[str, object]] = [
    {
        "name": "job_id",
        "label": "Job ID",
        "field": "job_id",
        "sortable": True,
        "align": "left",
    },
    {
        "name": "run_id",
        "label": "Run ID",
        "field": "run_id",
        "sortable": True,
        "align": "left",
    },
    {
        "name": "name",
        "label": "Name",
        "field": "name",
        "sortable": True,
        "align": "left",
    },
    {
        "name": "status",
        "label": "Status",
        "field": "status",
        "sortable": True,
        "align": "center",
    },
    {
        "name": "worker_id",
        "label": "Worker",
        "field": "worker_id",
        "sortable": True,
        "align": "left",
    },
    {
        "name": "actions",
        "label": "Actions",
        "field": "actions",
        "sortable": False,
        "align": "right",
    },
]


def _resolve_display_status(job: JobSpec) -> str:
    """Resolve user-facing badge status string for a JobSpec."""
    if job.state == JobState.DONE and job.outcome is not None:
        return str(job.outcome)
    if job.state == JobState.BLOCKED and job.status.reason == "Administratively held":
        return "HELD"
    return str(job.state)


def _filter_jobs(
    jobs: list[JobSpec],
    *,
    search_text: str = "",
    status_filter: str = "ALL",
) -> list[JobSpec]:
    """Filter jobs by search query and display status."""
    needle = search_text.strip().casefold()
    target_status = status_filter.strip().upper()
    filtered: list[JobSpec] = []
    for job in jobs:
        display_status = _resolve_display_status(job)
        if target_status not in ("", "ALL") and display_status != target_status:
            continue
        if needle:
            haystack = (
                f"{job.id} {job.run_id} {job.name} {job.assigned_worker_id or ''}"
            ).casefold()
            if needle not in haystack:
                continue
        filtered.append(job)
    return filtered


def _build_job_rows(jobs: list[JobSpec]) -> list[dict[str, object]]:
    """Transform JobSpec objects into sortable ui.table row dictionaries."""
    rows: list[dict[str, object]] = []
    for job in jobs:
        display_status = _resolve_display_status(job)
        is_terminal = display_status in _TERMINAL_DISPLAY_STATES
        rows.append(
            {
                "job_id": job.id,
                "run_id": job.run_id,
                "name": job.name,
                "status": display_status,
                "badge_bg": _STATUS_BADGE_COLORS.get(display_status, "#374151"),
                "worker_id": job.assigned_worker_id or "—",
                "can_hold": display_status in ("PENDING", "SUBMITTED"),
                "can_release": display_status == "HELD",
                "can_cancel": not is_terminal,
            }
        )
    return rows


async def _dispatch_lifecycle_action(
    pipeline: ExecutionPipeline,
    identity: Identity,
    action: str,
    target_id: str,
    on_mutated: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Dispatch Hold, Release, Cancel Job, or Cancel Run through ExecutionPipeline."""
    is_admin = "admin" in identity.roles
    cmd: HoldJobCommand | ReleaseJobCommand | CancelJobCommand | CancelRunCommand
    if action == "hold":
        cmd = HoldJobCommand(
            job_id=target_id, user_id=identity.user_id, elevate=is_admin
        )
    elif action == "release":
        cmd = ReleaseJobCommand(
            job_id=target_id, user_id=identity.user_id, elevate=is_admin
        )
    elif action == "cancel_run":
        cmd = CancelRunCommand(
            run_id=target_id, user_id=identity.user_id, elevate=is_admin
        )
    else:
        cmd = CancelJobCommand(
            job_id=target_id, user_id=identity.user_id, elevate=is_admin
        )

    try:
        await dispatch_command(pipeline, cmd)
        ui.notify(f"Action '{action}' succeeded for {target_id}", type="positive")
        if on_mutated is not None:
            await on_mutated()
        else:
            ui.navigate.reload()
    except Exception as exc:
        ui.notify(f"Action '{action}' failed: {exc}", type="negative")


def _open_cancel_run_dialog(
    run_id: str,
    on_confirm: Callable[[], Awaitable[None]],
) -> None:
    """Open an accessible confirmation dialog before cancelling an entire run."""
    with ui.dialog() as dialog, ui.card().classes("p-6 min-w-80"):
        ui.label(f"Cancel Run {run_id}?").classes("text-lg font-bold")
        ui.label(
            "All pending and running jobs in this run will be terminated."
        ).classes("text-sm text-slate-600 mt-1 mb-4")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Dismiss", on_click=dialog.close).props(
                'flat aria-label="Dismiss cancel run dialog"'
            )

            async def _confirm() -> None:
                dialog.close()
                await on_confirm()

            ui.button(
                "Confirm Cancel Run",
                on_click=_confirm,
                color="negative",
                icon="stop_circle",
            ).props(f'aria-label="Confirm cancel run {run_id}"')
    dialog.open()


async def _render_jobs_section(
    pipeline: ExecutionPipeline,
    identity: Identity,
    *,
    jobs: list[JobSpec] | None = None,
    on_mutated: Callable[[], Awaitable[None]] | None = None,
    filter_state: dict[str, str] | None = None,
) -> None:
    """Render sortable, filterable jobs table with status badges and lifecycle controls.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
        jobs: Optional pre-fetched list of JobSpec instances.
        on_mutated: Optional callback invoked after a job mutation succeeds.
        filter_state: Optional mutable dict persisting search/status filter values.
    """
    is_admin = "admin" in identity.roles
    resolved_jobs: list[JobSpec] = (
        jobs
        if jobs is not None
        else await dispatch_query(
            pipeline,
            ListJobsQuery(user_id=identity.user_id, elevate=is_admin),
        )
    )
    active_filters = (
        filter_state if filter_state is not None else {"search": "", "status": "ALL"}
    )
    ui.label("Jobs").classes("text-lg font-semibold mt-4")
    if not resolved_jobs:
        ui.label("No jobs in queue.").classes("text-slate-400")
        return

    filtered = _filter_jobs(
        resolved_jobs,
        search_text=active_filters.get("search", ""),
        status_filter=active_filters.get("status", "ALL"),
    )
    rows = _build_job_rows(filtered)

    table = ui.table(
        columns=_JOB_TABLE_COLUMNS,
        rows=rows,
        row_key="job_id",
        pagination={"rowsPerPage": 15, "sortBy": "job_id", "descending": False},
    ).classes("w-full mt-2")

    table.add_slot(
        "body-cell-status",
        """
        <q-td :props="props">
            <q-badge
                :style="{ backgroundColor: props.row.badge_bg, color: '#ffffff', fontWeight: 700 }"
                class="px-2 py-1 text-xs rounded"
            >
                {{ props.value }}
            </q-badge>
        </q-td>
        """,
    )
    table.add_slot(
        "body-cell-actions",
        """
        <q-td :props="props">
            <div class="row justify-end q-gutter-xs no-wrap">
                <q-btn
                    v-if="props.row.can_hold"
                    dense flat round size="sm" icon="pause_circle" color="purple-8"
                    :aria-label="'Hold job ' + props.row.job_id"
                    @click="$parent.$emit('hold_job', props.row)"
                >
                    <q-tooltip>Hold job</q-tooltip>
                </q-btn>
                <q-btn
                    v-if="props.row.can_release"
                    dense flat round size="sm" icon="play_circle" color="green-8"
                    :aria-label="'Release job ' + props.row.job_id"
                    @click="$parent.$emit('release_job', props.row)"
                >
                    <q-tooltip>Release job</q-tooltip>
                </q-btn>
                <q-btn
                    v-if="props.row.can_cancel"
                    dense flat round size="sm" icon="cancel" color="red-8"
                    :aria-label="'Kill job ' + props.row.job_id"
                    @click="$parent.$emit('cancel_job', props.row)"
                >
                    <q-tooltip>Kill job</q-tooltip>
                </q-btn>
                <q-btn
                    v-if="props.row.can_cancel"
                    dense flat round size="sm" icon="stop_circle" color="grey-8"
                    :aria-label="'Cancel run ' + props.row.run_id"
                    @click="$parent.$emit('cancel_run', props.row)"
                >
                    <q-tooltip>Cancel run</q-tooltip>
                </q-btn>
            </div>
        </q-td>
        """,
    )

    async def _on_hold(ev: object) -> None:
        args = getattr(ev, "args", {}) or {}
        await _dispatch_lifecycle_action(
            pipeline, identity, "hold", str(args.get("job_id", "")), on_mutated
        )

    async def _on_release(ev: object) -> None:
        args = getattr(ev, "args", {}) or {}
        await _dispatch_lifecycle_action(
            pipeline, identity, "release", str(args.get("job_id", "")), on_mutated
        )

    async def _on_cancel_job(ev: object) -> None:
        args = getattr(ev, "args", {}) or {}
        await _dispatch_lifecycle_action(
            pipeline, identity, "cancel_job", str(args.get("job_id", "")), on_mutated
        )

    def _on_cancel_run(ev: object) -> None:
        args = getattr(ev, "args", {}) or {}
        run_id = str(args.get("run_id", ""))
        _open_cancel_run_dialog(
            run_id,
            lambda: _dispatch_lifecycle_action(
                pipeline, identity, "cancel_run", run_id, on_mutated
            ),
        )

    table.on("hold_job", _on_hold)
    table.on("release_job", _on_release)
    table.on("cancel_job", _on_cancel_job)
    table.on("cancel_run", _on_cancel_run)


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


def _render_live_status_widget(script_url: str | None) -> None:
    """Render an accessible heartbeat badge polling `/dashboard/health`.

    Args:
        script_url: URL returned by `nicegui_app.add_static_file` for `live_status.js`.
    """
    ui.html(
        '<span id="hq-live-badge" role="status" aria-live="polite" '
        'style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;'
        "border-radius:9999px;font-size:0.75rem;font-weight:600;"
        'background-color:#15803d;color:#ffffff;">'
        '<span id="hq-live-dot" aria-hidden="true" '
        'style="width:8px;height:8px;border-radius:9999px;background-color:#86efac;">'
        "</span>"
        '<span id="hq-live-text">Connected</span>'
        "</span>",
        sanitize=False,
    )
    if script_url:
        ui.add_body_html(f'<script src="{script_url}" defer></script>')


async def _fetch_cluster_snapshot(
    pipeline: ExecutionPipeline,
    identity: Identity,
) -> tuple[ClusterStatsReport, list[NodeTelemetryPulse], list[JobSpec], str]:
    """Fetch cluster stats, active nodes, jobs, and a stable diff fingerprint."""
    is_admin = "admin" in identity.roles
    stats: ClusterStatsReport = await dispatch_query(pipeline, GetQueueStatsQuery())
    nodes: list[NodeTelemetryPulse] = await dispatch_query(pipeline, GetNodesQuery())
    jobs: list[JobSpec] = await dispatch_query(
        pipeline, ListJobsQuery(user_id=identity.user_id, elevate=is_admin)
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
        },
        sort_keys=True,
    )
    return stats, nodes, jobs, fingerprint


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
        tuple[ClusterStatsReport, list[NodeTelemetryPulse], list[JobSpec], str]
    ] = [await _fetch_cluster_snapshot(pipeline, identity)]
    filter_state: dict[str, str] = {"search": "", "status": "ALL"}

    def _notify_live_badge(changed: bool) -> None:
        flag = "true" if changed else "false"
        ui.run_javascript(
            "window.dispatchEvent(new CustomEvent('hq:cluster-update', "
            f"{{detail: {{changed: {flag}}}}}))"
        )

    async def _refresh_now(*, force: bool = False) -> None:
        _, _, _, prev_fp = snapshot_box[0]
        next_data = await _fetch_cluster_snapshot(pipeline, identity)
        changed = force or next_data[3] != prev_fp
        if changed:
            snapshot_box[0] = next_data
            _cluster_body.refresh()
        _notify_live_badge(changed)

    async def _handle_manual_refresh() -> None:
        await _refresh_now(force=True)

    async def _handle_timer_tick() -> None:
        await _refresh_now(force=False)

    @ui.refreshable
    async def _cluster_body() -> None:
        stats, nodes, jobs, _fp = snapshot_box[0]
        with ui.row().classes("w-full gap-4 mt-4"):
            with ui.card().classes("p-4"):
                ui.label(f"Total Jobs: {stats.total_jobs}").classes("font-semibold")
            with ui.card().classes("p-4"):
                ui.label(f"Running: {stats.running_jobs}").classes("font-semibold")
            with ui.card().classes("p-4"):
                ui.label(f"Pending: {stats.pending_jobs}").classes("font-semibold")
            with ui.card().classes("p-4"):
                ui.label(f"Active Nodes: {len(nodes)}").classes("font-semibold")

        await _render_jobs_section(
            pipeline,
            identity,
            jobs=jobs,
            on_mutated=_handle_manual_refresh,
            filter_state=filter_state,
        )

    with ui.header().classes("items-center justify-between px-6"):
        ui.label("Hexaqueue Operator Console").classes("text-lg font-bold")
        with ui.row().classes("items-center gap-3"):
            _render_live_status_widget(live_status_js_url)
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
            filter_state["search"] = str(getattr(ev, "value", "") or "")
            _cluster_body.refresh()

        def _on_status_change(ev: object) -> None:
            filter_state["status"] = str(getattr(ev, "value", "ALL") or "ALL")
            _cluster_body.refresh()

        ui.input(
            label="Search Jobs / Runs / Workers",
            placeholder="Filter by job ID, run ID, name, or worker...",
            on_change=_on_search_change,
        ).props(
            'clearable aria-label="Filter jobs by ID, run ID, name, or worker"'
        ).classes("w-80")
        ui.select(
            options=[
                "ALL",
                "PENDING",
                "RUNNING",
                "HELD",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "BLOCKED",
            ],
            value="ALL",
            label="Status Filter",
            on_change=_on_status_change,
        ).props('aria-label="Filter jobs by status"').classes("w-48")

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
        identity = _resolve_session_identity(manager)
        if identity is None:
            _render_login_panel(manager)
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
