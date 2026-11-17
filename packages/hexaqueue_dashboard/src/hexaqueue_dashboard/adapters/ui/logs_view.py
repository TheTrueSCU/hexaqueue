"""Live job execution log viewer shared by the slide-over drawer and dedicated page.

Provides XSS-safe `<pre>` log formatting, CQRS `GetLogsQuery` polling, a reusable
NiceGUI live-tail viewer component with pause/resume and manual refresh controls,
and a full-viewport `/dashboard/ui/logs/{job_id}` page.
"""

from __future__ import annotations

import html
from typing import Any

from hexastack_auth.domain.models import Identity
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_ui.adapters.nicegui import dispatch_query
from nicegui import ui

from hexaqueue_core.domain.cqrs import GetLogsQuery, ListJobsQuery
from hexaqueue_core.domain.lifecycle import JobState
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_dashboard.adapters.ui.status import (
    STATUS_BADGE_COLORS,
    resolve_job_display_status,
)


def format_log_lines(logs: list[LogChunk], logs_error: str | None) -> str:
    """Format log chunks or fallback diagnostics into HTML-escaped `<pre>` text.

    Args:
        logs: List of `LogChunk` items returned by `GetLogsQuery`.
        logs_error: Optional error message if log retrieval failed.

    Returns:
        HTML-escaped string suitable for rendering inside a `<pre>` block.

    Notes/Architectural Intent:
        Escapes arbitrary stdout/stderr characters before inserting into
        `ui.html(..., sanitize=False)` to prevent HTML injection from job output.
    """
    if logs:
        raw = "\n".join(f"[{chunk.stream}] {chunk.content}" for chunk in logs)
    elif logs_error:
        raw = f"Logs unavailable: {logs_error}"
    else:
        raw = "No logs recorded yet."
    return html.escape(raw)


def build_log_pre_html(
    logs: list[LogChunk],
    logs_error: str | None,
    *,
    max_height: str = "260px",
) -> str:
    """Render an accessible dark-slate `<pre>` block containing formatted job logs.

    Args:
        logs: LogChunk sequence from `GetLogsQuery`.
        logs_error: Optional error message if fetching logs failed.
        max_height: CSS `max-height` value for the scrollable log viewport.

    Returns:
        HTML string containing a styled `<pre>` element.

    Notes/Architectural Intent:
        Uses high-contrast `#f8fafc` foreground on `#0f172a` background to exceed
        WCAG 2.1 AA 4.5:1 contrast requirements.
    """
    escaped = format_log_lines(logs, logs_error)
    return (
        '<pre aria-label="Job execution logs" '
        'style="background-color:#0f172a;color:#f8fafc;padding:12px;'
        "border-radius:6px;font-size:0.75rem;overflow:auto;"
        f'max-height:{max_height};white-space:pre-wrap;">{escaped}</pre>'
    )


async def fetch_job_logs(
    pipeline: ExecutionPipeline,
    identity: Identity,
    job_id: str,
) -> tuple[list[LogChunk], str | None]:
    """Fetch execution log chunks for a job via the CQRS `GetLogsQuery`.

    Args:
        pipeline: Shared CQRS `ExecutionPipeline`.
        identity: Authenticated operator `Identity`.
        job_id: Target job identifier.

    Returns:
        Tuple of `(logs, logs_error)` where `logs_error` is `None` on success.

    Notes/Architectural Intent:
        Routes all log reads through `ExecutionPipeline` so RBAC policies and
        audit instrumentation remain uniform across the console.
    """
    try:
        logs = await dispatch_query(
            pipeline,
            GetLogsQuery(job_id=job_id),
        )
        return list(logs), None
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)


def render_live_log_viewer(
    logs: list[LogChunk],
    logs_error: str | None,
    *,
    pipeline: ExecutionPipeline | None = None,
    identity: Identity | None = None,
    job_id: str | None = None,
    default_live_tail: bool = False,
    full_page_url: str | None = None,
    max_height: str = "260px",
    heading: str = "Execution Logs",
) -> Any:
    """Render an execution log viewer with optional live-tail polling and full-page link.

    Args:
        logs: Initial `LogChunk` list to display immediately.
        logs_error: Optional error string from the initial `GetLogsQuery`.
        pipeline: Optional CQRS `ExecutionPipeline` for live polling and refresh.
        identity: Optional authenticated operator `Identity`.
        job_id: Optional job identifier to poll with `GetLogsQuery`.
        default_live_tail: Whether live-tail polling starts active.
        full_page_url: Optional URL to open the dedicated full-page log viewer.
        max_height: CSS `max-height` applied to the `<pre>` viewport.
        heading: Section heading label rendered above the log viewport.

    Returns:
        The created `ui.html` element (or `None` in headless fakes), allowing
        callers to inspect or test rendered content.

    Notes/Architectural Intent:
        Updates `log_box.content` in place rather than clearing parent cards so
        live log polling never steals keyboard focus or flickers the drawer.
    """
    can_poll = pipeline is not None and identity is not None and bool(job_id)

    with ui.row().classes("w-full items-center justify-between gap-2 mt-4"):
        ui.label(heading).classes("text-sm font-semibold")
        with ui.row().classes("items-center gap-2"):
            if can_poll:
                tail_switch = ui.switch("Live Tail", value=default_live_tail).props(
                    'dense aria-label="Toggle live log tail"'
                )
            else:
                tail_switch = None

            if full_page_url:
                ui.button(
                    "Open Page",
                    icon="open_in_new",
                    on_click=lambda: ui.navigate.to(full_page_url, new_tab=True),
                ).props(
                    'flat dense size=sm color="grey-3" '
                    'aria-label="Open dedicated live log page"'
                )

    log_box = ui.html(
        build_log_pre_html(logs, logs_error, max_height=max_height),
        sanitize=False,
    )

    if pipeline is not None and identity is not None and job_id:
        active_pipeline = pipeline
        active_identity = identity
        active_job_id = job_id

        async def _refresh_logs() -> None:
            latest_logs, latest_err = await fetch_job_logs(
                active_pipeline, active_identity, active_job_id
            )
            log_box.content = build_log_pre_html(
                latest_logs, latest_err, max_height=max_height
            )
            if hasattr(log_box, "update"):
                log_box.update()

        ui.button(
            "Refresh Logs",
            icon="refresh",
            on_click=_refresh_logs,
        ).props(
            'flat dense size=sm color="grey-3" aria-label="Refresh job logs"'
        ).classes("mt-1")

        if hasattr(ui, "timer"):
            timer = ui.timer(2.0, _refresh_logs, active=default_live_tail)
            if tail_switch is not None and hasattr(tail_switch, "on_value_change"):
                tail_switch.on_value_change(
                    lambda ev: setattr(
                        timer, "active", bool(getattr(ev, "value", False))
                    )
                )

    return log_box


async def render_live_logs_page(
    pipeline: ExecutionPipeline,
    identity: Identity,
    job_id: str,
    *,
    back_url: str = "/dashboard/ui",
) -> None:
    """Render the dedicated full-viewport live log streaming page for a job.

    Args:
        pipeline: Shared CQRS `ExecutionPipeline`.
        identity: Authenticated operator `Identity`.
        job_id: Target job identifier from the route path.
        back_url: URL of the main operator console for back-navigation.

    Notes/Architectural Intent:
        Provides a focused single-job live tail workspace with semantic
        `<header>` and `<main>` landmarks for WCAG 2.1 AA compliance.
    """
    logs, logs_error = await fetch_job_logs(pipeline, identity, job_id)
    job = None
    try:
        is_admin = "admin" in identity.roles
        jobs = await dispatch_query(
            pipeline, ListJobsQuery(user_id=identity.user_id, elevate=is_admin)
        )
        job = next((item for item in jobs if item.id == job_id), None)
    except Exception:  # noqa: BLE001
        job = None

    default_tail = job is not None and job.status.state in {
        JobState.RUNNING,
        JobState.PROVISIONING,
    }

    with (
        ui.element("header").classes(
            "w-full px-6 py-4 bg-slate-900 border-b border-slate-800 "
            "flex items-center justify-between gap-4"
        ),
        ui.row().classes("items-center gap-3"),
    ):
        ui.button(
            "Back to Dashboard",
            icon="arrow_back",
            on_click=lambda: ui.navigate.to(back_url),
        ).props('flat color="grey-3" aria-label="Back to operator dashboard"')
        ui.html(
            f'<h1 class="text-xl font-bold text-slate-50 m-0">'
            f"Live Log Stream: {html.escape(job_id)}</h1>",
            sanitize=False,
        )
        if job is not None:
            badge_label = resolve_job_display_status(job.status)
            badge_color = STATUS_BADGE_COLORS.get(badge_label, "grey")
            ui.badge(badge_label, color=badge_color).props(
                f'aria-label="Job status {badge_label}"'
            )

    with ui.element("main").classes("w-full max-w-6xl mx-auto px-6 py-4"):
        if job is not None:
            ui.label(
                f"Job: {job.name} | Run: {job.run_id} | Command: {job.command}"
            ).classes("text-xs font-mono text-slate-300")
        render_live_log_viewer(
            logs,
            logs_error,
            pipeline=pipeline,
            identity=identity,
            job_id=job_id,
            default_live_tail=default_tail,
            max_height="calc(100vh - 230px)",
            heading="Live Execution Log Tail",
        )


__all__ = [
    "build_log_pre_html",
    "fetch_job_logs",
    "format_log_lines",
    "render_live_log_viewer",
    "render_live_logs_page",
]
