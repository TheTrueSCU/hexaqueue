"""NiceGUI reactive operator console adapter for Hexaqueue Dashboard.

Notes/Architectural Intent:
    Builds on `hexastack-ui` (`mount_ui_app`, `ui_page`, `dispatch_command`,
    `dispatch_query`) and `hexastack-auth` (`DashboardAuthManager`) to provide
    an authenticated operator console at `/dashboard/ui` over HTTPS (Tailscale
    Serve) or SSH tunnels.
"""

from __future__ import annotations

import importlib.resources
import logging
import os
import secrets
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
    ClusterStatsReport,
    GetNodesQuery,
    GetQueueStatsQuery,
    ListJobsQuery,
)
from hexaqueue_core.domain.job import JobSpec
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


async def _render_jobs_section(
    pipeline: ExecutionPipeline,
    identity: Identity,
) -> None:
    """Render active cluster jobs table with RBAC-gated Kill controls.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
    """
    is_admin = "admin" in identity.roles
    jobs: list[JobSpec] = await dispatch_query(
        pipeline,
        ListJobsQuery(user_id=identity.user_id, elevate=is_admin),
    )
    ui.label("Jobs").classes("text-lg font-semibold mt-4")
    if not jobs:
        ui.label("No jobs in queue.").classes("text-slate-400")
        return

    for job in jobs:
        with ui.row().classes("w-full items-center justify-between border-b py-2"):
            ui.label(f"{job.id} | {job.run_id} | {job.name} ({job.state})").classes(
                "font-mono text-sm"
            )

            async def _kill_job(target_id: str = job.id) -> None:
                try:
                    await dispatch_command(
                        pipeline,
                        CancelJobCommand(
                            job_id=target_id,
                            user_id=identity.user_id,
                            elevate=is_admin,
                        ),
                    )
                    ui.notify(f"Cancelled job {target_id}", type="positive")
                    ui.navigate.reload()
                except Exception as exc:
                    ui.notify(f"Cancel failed: {exc}", type="negative")

            ui.button(
                "Kill", on_click=_kill_job, icon="cancel", color="negative"
            ).props(f'aria-label="Kill job {job.id}"').tooltip(f"Cancel job {job.id}")


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
        '<span id="hq-live-text">Live</span>'
        "</span>",
        sanitize=False,
    )
    if script_url:
        ui.add_body_html(f'<script src="{script_url}" defer></script>')


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
    with ui.header().classes("items-center justify-between px-6"):
        ui.label("Hexaqueue Operator Console").classes("text-lg font-bold")
        with ui.row().classes("items-center gap-3"):
            _render_live_status_widget(live_status_js_url)
            ui.label(f"{identity.user_id} ({roles_label})").classes("text-sm")
            ui.button(
                "Refresh",
                on_click=ui.navigate.reload,
                icon="refresh",
            ).props('aria-label="Refresh cluster status"').tooltip("Refresh status")

            def _logout() -> None:
                nicegui_app.storage.user.pop("jwt", None)
                ui.navigate.reload()

            ui.button("Sign Out", on_click=_logout, icon="logout").props(
                'aria-label="Sign out"'
            ).tooltip("Sign out")

    stats: ClusterStatsReport = await dispatch_query(pipeline, GetQueueStatsQuery())
    nodes: list[NodeTelemetryPulse] = await dispatch_query(pipeline, GetNodesQuery())
    with ui.row().classes("w-full gap-4 mt-4"):
        with ui.card().classes("p-4"):
            ui.label(f"Total Jobs: {stats.total_jobs}").classes("font-semibold")
        with ui.card().classes("p-4"):
            ui.label(f"Running: {stats.running_jobs}").classes("font-semibold")
        with ui.card().classes("p-4"):
            ui.label(f"Pending: {stats.pending_jobs}").classes("font-semibold")
        with ui.card().classes("p-4"):
            ui.label(f"Active Nodes: {len(nodes)}").classes("font-semibold")

    await _render_jobs_section(pipeline, identity)


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
