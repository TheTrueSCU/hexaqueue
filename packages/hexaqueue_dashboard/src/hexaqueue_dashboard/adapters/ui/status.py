"""Status badge palette, lifecycle roll-ups, and live tunnel widget.

Notes/Architectural Intent:
    Centralizes WCAG 2.1 AA high-contrast status colors and job/run display
    status roll-up logic shared across the Runs tree, Jobs table, and drawer.
"""

from __future__ import annotations

from nicegui import ui

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, RunState
from hexaqueue_server.domain.models import RunStatusReport

STATUS_BADGE_COLORS: dict[str, str] = {
    "RUNNING": "#1d4ed8",
    "CLEANUP": "#1d4ed8",
    "PENDING": "#92400e",
    "SUBMITTED": "#92400e",
    "PROVISIONING": "#92400e",
    "HELD": "#6b21a8",
    "IN_PROGRESS": "#0f766e",
    "COMPLETED": "#15803d",
    "SUCCEEDED": "#15803d",
    "FAILED": "#b91c1c",
    "PARTIALLY_FAILED": "#b91c1c",
    "TIMED_OUT": "#b91c1c",
    "BLOCKED": "#b91c1c",
    "CANCELLED": "#374151",
}

TERMINAL_DISPLAY_STATES: frozenset[str] = frozenset(
    {"COMPLETED", "FAILED", "TIMED_OUT", "CANCELLED", "SUCCEEDED", "PARTIALLY_FAILED"}
)

STATUS_SORT_RANK: dict[str, int] = {
    "RUNNING": 0,
    "PROVISIONING": 1,
    "CLEANUP": 2,
    "IN_PROGRESS": 3,
    "PENDING": 4,
    "SUBMITTED": 5,
    "HELD": 6,
    "BLOCKED": 7,
    "FAILED": 8,
    "PARTIALLY_FAILED": 9,
    "TIMED_OUT": 10,
    "CANCELLED": 11,
    "SUCCEEDED": 12,
    "COMPLETED": 13,
}


def status_sort_rank(display_status: str) -> int:
    """Return semantic sort priority for a display status string.

    Args:
        display_status: Normalized display status (e.g. ``RUNNING``, ``PENDING``).

    Returns:
        Integer rank where active/pending/blocked/failed sort before terminal
        completed states.

    Notes/Architectural Intent:
        Replaces alphabetical status sorting so operators see live, queued,
        and failing work before historical completed items.
    """
    return STATUS_SORT_RANK.get(display_status.strip().upper(), 99)


def resolve_job_display_status(job: JobSpec) -> str:
    """Resolve user-facing badge status string for a JobSpec.

    Args:
        job: Target JobSpec domain model.

    Returns:
        Normalized display status string (e.g., ``HELD``, ``COMPLETED``, ``RUNNING``).
    """
    if job.state == JobState.DONE and job.outcome is not None:
        return str(job.outcome)
    if job.state == JobState.BLOCKED and job.status.reason == "Administratively held":
        return "HELD"
    return str(job.state)


def resolve_run_display_status(run: RunStatusReport) -> str:
    """Resolve user-facing badge status string for a RunStatusReport.

    Distinguishes ``PENDING`` (all pending, 0 running/completed), ``RUNNING``
    (1+ jobs actively running), ``IN_PROGRESS`` (mixed completed and pending
    with 0 currently running), and terminal/blocked states.

    Args:
        run: Aggregated RunStatusReport instance.

    Returns:
        Normalized display status string.
    """
    if run.outcome is not None:
        return str(run.outcome)
    if run.state == RunState.BLOCKED:
        return "BLOCKED"
    if run.running_jobs > 0:
        return "RUNNING"
    if run.completed_jobs + run.failed_jobs == 0:
        return "PENDING" if run.pending_jobs > 0 else str(run.state)
    if run.pending_jobs > 0:
        return "IN_PROGRESS"
    return str(run.state)


def render_live_status_widget(script_url: str | None, *, mode: str = "full") -> None:
    """Render an accessible heartbeat badge polling `/dashboard/health` and SSE.

    Args:
        script_url: URL returned by `nicegui_app.add_static_file` for `live_status.js`.
        mode: Display mode (`"full"` for console SSE + timestamps, `"tunnel"` for login).
    """
    initial_text = "Tunnel Connected" if mode == "tunnel" else "Connected"
    ui.html(
        f'<span id="hq-live-badge" data-mode="{mode}" role="status" aria-live="polite" '
        'style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;'
        "border-radius:9999px;font-size:0.75rem;font-weight:600;"
        'background-color:#15803d;color:#ffffff;">'
        '<span id="hq-live-dot" aria-hidden="true" '
        'style="width:8px;height:8px;border-radius:9999px;background-color:#86efac;">'
        "</span>"
        f'<span id="hq-live-text">{initial_text}</span>'
        "</span>",
        sanitize=False,
    )
    if script_url:
        ui.add_body_html(f'<script src="{script_url}" defer></script>')


def matches_status_filter(display_status: str, target_status: str) -> bool:
    """Evaluate whether a display status matches a filter key or group.

    Args:
        display_status: Normalized display status string (e.g. ``RUNNING``).
        target_status: Filter key (``ALL``, ``ACTIVE``, ``TERMINAL``, ``INACTIVE``,
            or an exact status string).

    Returns:
        ``True`` if the status matches the filter, otherwise ``False``.

    Notes/Architectural Intent:
        Shared by both the Jobs table and Runs tree so ``ACTIVE`` (non-terminal)
        and ``TERMINAL`` / ``INACTIVE`` grouped filters behave uniformly.
    """
    normalized = target_status.strip().upper()
    if normalized in ("", "ALL"):
        return True
    if normalized == "ACTIVE":
        return display_status not in TERMINAL_DISPLAY_STATES
    if normalized in ("TERMINAL", "INACTIVE"):
        return display_status in TERMINAL_DISPLAY_STATES
    return display_status == normalized


__all__ = [
    "matches_status_filter",
    "render_live_status_widget",
    "resolve_job_display_status",
    "resolve_run_display_status",
    "STATUS_BADGE_COLORS",
    "status_sort_rank",
    "STATUS_SORT_RANK",
    "TERMINAL_DISPLAY_STATES",
]
