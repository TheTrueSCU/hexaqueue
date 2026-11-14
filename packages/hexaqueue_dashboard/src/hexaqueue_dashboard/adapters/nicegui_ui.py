"""NiceGUI reactive operator console adapter for Hexaqueue Dashboard.

Notes/Architectural Intent:
    Builds on `hexastack-ui` (`mount_ui_app`, `ui_page`, `dispatch_command`,
    `dispatch_query`) and `hexastack-auth` (`DashboardAuthManager`) to provide
    an authenticated operator console at `/dashboard/ui` over HTTPS (Tailscale
    Serve) or SSH tunnels.
"""

from __future__ import annotations

from fastapi import FastAPI
from hexastack_auth.domain.models import Identity
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_ui.adapters.nicegui import (
    dispatch_command,
    dispatch_query,
    mount_ui_app,
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

            ui.button("Kill", on_click=_kill_job, icon="cancel", color="red").props(
                f'aria-label="Kill job {job.id}"'
            ).tooltip(f"Cancel job {job.id}")


async def _render_console_panel(
    pipeline: ExecutionPipeline,
    identity: Identity,
) -> None:
    """Render the authenticated Hexaqueue operator console.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
    """
    roles_label = ", ".join(sorted(identity.roles))
    with ui.header().classes("items-center justify-between px-6"):
        ui.label("Hexaqueue Operator Console").classes("text-lg font-bold")
        with ui.row().classes("items-center gap-3"):
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

    @ui_page(mount_path, title="Hexaqueue Operator Console", dark=True)
    async def _dashboard_page() -> None:
        identity = _resolve_session_identity(manager)
        if identity is None:
            _render_login_panel(manager)
            return
        await _render_console_panel(pipeline, identity)

    mount_ui_app(app, title="Hexaqueue Operator Console", dark=True)


__all__ = [
    "mount_dashboard_ui",
]
