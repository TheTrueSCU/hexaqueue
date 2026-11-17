"""Unified slide-over inspection drawer and CQRS lifecycle action helpers.

Notes/Architectural Intent:
    Provides polymorphic Run and Job inspection overlays (ExplainJobQuery,
    GetLogsQuery, DAG parent/child navigation, and Hold/Release/Kill/Cancel Run)
    routed strictly through `ExecutionPipeline` without deep page navigation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from typing import Any

from hexastack_auth.domain.models import Identity
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_ui.adapters.nicegui import dispatch_command, dispatch_query
from nicegui import ui

from hexaqueue_core.domain.cqrs import (
    CancelJobCommand,
    CancelRunCommand,
    ExplainJobQuery,
    GetLogsQuery,
    HoldJobCommand,
    ReleaseJobCommand,
)
from hexaqueue_core.domain.explainability import SchedulingDecisionReport
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_dashboard.adapters.ui.status import (
    STATUS_BADGE_COLORS,
    TERMINAL_DISPLAY_STATES,
    resolve_job_display_status,
    resolve_run_display_status,
)
from hexaqueue_server.domain.models import RunStatusReport


async def dispatch_lifecycle_action(
    pipeline: ExecutionPipeline,
    identity: Identity,
    action: str,
    target_id: str,
    on_mutated: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Dispatch Hold, Release, Cancel Job, or Cancel Run through ExecutionPipeline.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
        action: Action name (``hold``, ``release``, ``cancel_run``, ``cancel_job``).
        target_id: Target job or run identifier.
        on_mutated: Optional async callback invoked after successful mutation.
    """
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


def open_cancel_run_dialog(
    run_id: str,
    on_confirm: Callable[[], Awaitable[None]],
) -> None:
    """Open an accessible confirmation dialog before cancelling an entire run.

    Args:
        run_id: Target pipeline run identifier.
        on_confirm: Async callback executed when operator confirms cancellation.
    """
    with ui.dialog() as dialog, ui.card().classes("p-6 min-w-80"):
        ui.label(f"Cancel Run {run_id}?").classes("text-lg font-bold")
        ui.label(
            "All pending and running jobs in this run will be terminated."
        ).classes("text-sm text-slate-300 mt-1 mb-4")
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


def render_drawer_dag_links(
    drawer: Any,
    pipeline: ExecutionPipeline,
    identity: Identity,
    job: JobSpec,
    *,
    run_report: RunStatusReport | None,
    all_jobs: list[JobSpec] | None,
    on_mutated: Callable[[], Awaitable[None]] | None,
    on_filter_run: Callable[[str], None] | None,
) -> None:
    """Render clickable upstream parent and downstream child job navigation buttons.

    Args:
        drawer: Active NiceGUI dialog instance.
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
        job: Currently inspected JobSpec.
        run_report: Parent RunStatusReport if available.
        all_jobs: All jobs in the current snapshot for resolving links.
        on_mutated: Optional mutation callback.
        on_filter_run: Optional run filter callback.
    """
    jobs_by_id = {j.id: j for j in (all_jobs or [])}
    parents = run_report.dependencies.get(job.id, []) if run_report else []
    children = [
        cid
        for cid, p_list in (run_report.dependencies.items() if run_report else [])
        if job.id in p_list
    ]
    if not parents and not children:
        return

    ui.label("DAG Relationships").classes("text-sm font-semibold mt-4")
    with ui.row().classes("w-full flex-wrap gap-2 mt-1"):
        for pid in parents:
            parent_job = jobs_by_id.get(pid)
            if parent_job is not None:

                async def _jump_parent(target: JobSpec = parent_job) -> None:
                    drawer.close()
                    await open_job_inspection_drawer(
                        pipeline,
                        identity,
                        target,
                        run_report=run_report,
                        all_jobs=all_jobs,
                        on_mutated=on_mutated,
                        on_filter_run=on_filter_run,
                    )

                ui.button(f"Parent: {pid}", on_click=_jump_parent).props(
                    f'size="sm" color="primary" aria-label="Inspect parent job {pid}"'
                )
        for cid in children:
            child_job = jobs_by_id.get(cid)
            if child_job is not None:

                async def _jump_child(target: JobSpec = child_job) -> None:
                    drawer.close()
                    await open_job_inspection_drawer(
                        pipeline,
                        identity,
                        target,
                        run_report=run_report,
                        all_jobs=all_jobs,
                        on_mutated=on_mutated,
                        on_filter_run=on_filter_run,
                    )

                ui.button(f"Child: {cid}", on_click=_jump_child).props(
                    f'size="sm" color="primary" aria-label="Inspect child job {cid}"'
                )


def _fmt_ts(ts: Any) -> str:
    """Format an optional datetime timestamp for timeline display.

    Args:
        ts: Optional datetime or ISO string.

    Returns:
        Formatted UTC timestamp string or ``unknown``.

    Notes/Architectural Intent:
        Keeps timeline rendering resilient when unit-test fixtures omit
        or supply naive datetimes.
    """
    if ts is None:
        return "unknown"
    if hasattr(ts, "strftime"):
        return str(ts.strftime("%Y-%m-%d %H:%M:%S UTC"))
    return str(ts)


def render_drawer_state_timeline(job: JobSpec) -> None:
    """Render chronological state-change event log for a job.

    Args:
        job: Target JobSpec whose lifecycle timestamps are displayed.

    Notes/Architectural Intent:
        Present from the moment a job enters the system (creation timestamp)
        and tracks worker assignment and latest state transition/reason.
    """
    display_status = resolve_job_display_status(job)
    events: list[tuple[str, str]] = [
        (_fmt_ts(job.created_at), "Created / Submitted (PENDING)"),
    ]
    if job.assigned_worker_id:
        events.append(
            (_fmt_ts(job.updated_at), f"Assigned to worker {job.assigned_worker_id}")
        )
    reason_suffix = f" ({job.status.reason})" if job.status.reason else ""
    if display_status != "PENDING" or reason_suffix:
        events.append(
            (_fmt_ts(job.updated_at), f"State: {display_status}{reason_suffix}")
        )

    ui.label("State Timeline").classes("text-sm font-semibold mt-4")
    with ui.column().classes("w-full gap-1 mt-1 pl-3 border-l-2 border-slate-600"):
        for timestamp_str, description in events:
            ui.label(f"{timestamp_str} — {description}").classes(
                "text-xs font-mono text-slate-200"
            )


def render_drawer_explain_and_logs(
    explain_report: SchedulingDecisionReport | None,
    explain_error: str | None,
    logs: list[LogChunk],
    logs_error: str | None,
    *,
    show_explainability: bool = True,
) -> None:
    """Render scheduler explainability summary and execution log tail.

    Args:
        explain_report: Optional SchedulingDecisionReport from ExplainJobQuery.
        explain_error: Optional error message if explainability failed.
        logs: LogChunk list from GetLogsQuery.
        logs_error: Optional error message if log retrieval failed.
        show_explainability: Whether to display the Scheduler Explainability
            section (omitted once a job is running or terminal).

    Notes/Architectural Intent:
        Hides pre-dispatch queue/slot explainability once a job has moved past
        pending/blocked states so operators see only relevant execution details.
    """
    if show_explainability:
        ui.label("Scheduler Explainability").classes("text-sm font-semibold mt-4")
        if explain_report is not None:
            ui.label(explain_report.summary).classes("text-sm text-slate-100 mt-1")
            ui.label(
                f"Queue Position: {explain_report.queue_position}/{explain_report.queue_total} | "
                f"Slots: {explain_report.available_slots}/{explain_report.total_slots} "
                f"(Required: {explain_report.required_slots})"
            ).classes("text-xs font-mono text-slate-300 mt-1")
        else:
            ui.label(f"Explainability unavailable: {explain_error}").classes(
                "text-xs text-slate-300 mt-1"
            )

    ui.label("Execution Logs").classes("text-sm font-semibold mt-4")
    if logs:
        rendered_lines = "\n".join(
            f"[{chunk.stream}] {chunk.content}" for chunk in logs
        )
    elif logs_error:
        rendered_lines = f"Logs unavailable: {logs_error}"
    else:
        rendered_lines = "No logs recorded yet."
    ui.html(
        '<pre aria-label="Job execution logs" '
        'style="background-color:#0f172a;color:#f8fafc;padding:12px;'
        "border-radius:6px;font-size:0.75rem;overflow-x:auto;"
        f'max-height:260px;">{rendered_lines}</pre>',
        sanitize=False,
    )


async def open_job_inspection_drawer(
    pipeline: ExecutionPipeline,
    identity: Identity,
    job: JobSpec,
    *,
    run_report: RunStatusReport | None = None,
    all_jobs: list[JobSpec] | None = None,
    on_mutated: Callable[[], Awaitable[None]] | None = None,
    on_filter_run: Callable[[str], None] | None = None,
    drawer_host: Any = None,
) -> None:
    """Open slide-over inspection drawer for a job (logs, explainability, DAG links).

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
        job: Target JobSpec to inspect.
        run_report: Optional parent RunStatusReport.
        all_jobs: Optional list of all jobs for DAG link resolution.
        on_mutated: Optional async callback invoked after lifecycle mutations.
        on_filter_run: Optional callback to filter the jobs table to a run ID.
        drawer_host: Optional persistent NiceGUI container outside refreshable blocks.
    """
    is_admin = "admin" in identity.roles
    display_status = resolve_job_display_status(job)
    badge_bg = STATUS_BADGE_COLORS.get(display_status, "#374151")
    show_explainability = (
        display_status not in ("RUNNING", "CLEANUP")
        and display_status not in TERMINAL_DISPLAY_STATES
    )

    explain_report: SchedulingDecisionReport | None = None
    explain_error: str | None = None
    if show_explainability:
        try:
            explain_report = await dispatch_query(
                pipeline, ExplainJobQuery(job_id=job.id)
            )
        except Exception as exc:
            explain_error = str(exc)

    logs: list[LogChunk] = []
    logs_error: str | None = None
    try:
        logs = await dispatch_query(
            pipeline,
            GetLogsQuery(
                job_id=job.id, tail=50, user_id=identity.user_id, elevate=is_admin
            ),
        )
    except Exception as exc:
        logs_error = str(exc)

    host_ctx: Any = nullcontext()
    if drawer_host is not None:
        drawer_host.clear()
        host_ctx = drawer_host

    with (
        host_ctx,
        ui.dialog().props("position=right full-height") as drawer,
        ui.card().classes("w-[520px] max-w-full h-full overflow-y-auto p-6"),
    ):
        with ui.row().classes("w-full items-center justify-between mb-3"):
            ui.label(f"Job: {job.name}").classes("text-lg font-bold")
            ui.button("Close", on_click=drawer.close, icon="close").props(
                'flat aria-label="Close inspection drawer"'
            )

        ui.html(
            f'<span style="display:inline-block;padding:3px 10px;border-radius:6px;'
            f"font-size:0.75rem;font-weight:700;background-color:{badge_bg};"
            f'color:#ffffff;">{display_status}</span>',
            sanitize=False,
        )
        ui.label(f"Job ID: {job.id} | Run ID: {job.run_id}").classes(
            "font-mono text-xs text-slate-300 mt-2"
        )
        ui.label(f"Command: {job.command}").classes("font-mono text-xs text-slate-300")

        with ui.row().classes("w-full flex-wrap gap-2 mt-3"):
            if on_filter_run is not None:

                def _filter_to_run() -> None:
                    drawer.close()
                    on_filter_run(job.run_id)

                ui.button(
                    "Filter Table to Run", on_click=_filter_to_run, icon="filter_alt"
                ).props(
                    'size="sm" color="primary" aria-label="Filter jobs table to this run"'
                )

            if run_report is not None:

                async def _jump_to_run() -> None:
                    drawer.close()
                    await open_run_inspection_drawer(
                        pipeline,
                        identity,
                        run_report,
                        all_jobs or [],
                        on_mutated=on_mutated,
                        on_filter_run=on_filter_run,
                    )

                ui.button(
                    "Inspect Run", on_click=_jump_to_run, icon="account_tree"
                ).props('size="sm" color="primary" aria-label="Inspect parent run"')

            if display_status not in TERMINAL_DISPLAY_STATES:

                async def _kill_this() -> None:
                    drawer.close()
                    await dispatch_lifecycle_action(
                        pipeline, identity, "cancel_job", job.id, on_mutated
                    )

                ui.button(
                    "Kill Job", on_click=_kill_this, icon="cancel", color="negative"
                ).props('size="sm" aria-label="Kill inspected job"')

        render_drawer_dag_links(
            drawer,
            pipeline,
            identity,
            job,
            run_report=run_report,
            all_jobs=all_jobs,
            on_mutated=on_mutated,
            on_filter_run=on_filter_run,
        )
        render_drawer_state_timeline(job)
        render_drawer_explain_and_logs(
            explain_report,
            explain_error,
            logs,
            logs_error,
            show_explainability=show_explainability,
        )

    drawer.open()


async def open_run_inspection_drawer(
    pipeline: ExecutionPipeline,
    identity: Identity,
    run_report: RunStatusReport,
    all_jobs: list[JobSpec],
    *,
    on_mutated: Callable[[], Awaitable[None]] | None = None,
    on_filter_run: Callable[[str], None] | None = None,
    drawer_host: Any = None,
) -> None:
    """Open slide-over inspection drawer for a pipeline Run and its child jobs.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
        run_report: Target RunStatusReport instance.
        all_jobs: All jobs in the current snapshot.
        on_mutated: Optional async callback invoked after lifecycle mutations.
        on_filter_run: Optional callback to filter the jobs table to a run ID.
        drawer_host: Optional persistent NiceGUI container outside refreshable blocks.
    """
    run_status = resolve_run_display_status(run_report)
    badge_bg = STATUS_BADGE_COLORS.get(run_status, "#374151")
    run_jobs = [j for j in all_jobs if j.run_id == run_report.run_id]

    host_ctx: Any = nullcontext()
    if drawer_host is not None:
        drawer_host.clear()
        host_ctx = drawer_host

    with (
        host_ctx,
        ui.dialog().props("position=right full-height") as drawer,
        ui.card().classes("w-[520px] max-w-full h-full overflow-y-auto p-6"),
    ):
        with ui.row().classes("w-full items-center justify-between mb-3"):
            ui.label(f"Run: {run_report.name or run_report.run_id}").classes(
                "text-lg font-bold"
            )
            ui.button("Close", on_click=drawer.close, icon="close").props(
                'flat aria-label="Close inspection drawer"'
            )

        ui.html(
            f'<span style="display:inline-block;padding:3px 10px;border-radius:6px;'
            f"font-size:0.75rem;font-weight:700;background-color:{badge_bg};"
            f'color:#ffffff;">{run_status}</span>',
            sanitize=False,
        )
        ui.label(
            f"Run ID: {run_report.run_id} | "
            f"Completed: {run_report.completed_jobs}/{run_report.total_jobs} | "
            f"Running: {run_report.running_jobs} | Failed: {run_report.failed_jobs}"
        ).classes("font-mono text-xs text-slate-300 mt-2")

        with ui.row().classes("w-full flex-wrap gap-2 mt-3"):
            if on_filter_run is not None:

                def _filter_to_run() -> None:
                    drawer.close()
                    on_filter_run(run_report.run_id)

                ui.button(
                    "Filter Jobs Table to Run",
                    on_click=_filter_to_run,
                    icon="filter_alt",
                ).props(
                    'size="sm" color="primary" aria-label="Filter jobs table to this run"'
                )

            has_outstanding = (run_report.pending_jobs + run_report.running_jobs) > 0
            if run_status not in TERMINAL_DISPLAY_STATES and has_outstanding:

                def _cancel_this_run() -> None:
                    drawer.close()
                    open_cancel_run_dialog(
                        run_report.run_id,
                        lambda: dispatch_lifecycle_action(
                            pipeline,
                            identity,
                            "cancel_run",
                            run_report.run_id,
                            on_mutated,
                        ),
                    )

                ui.button(
                    "Cancel Run",
                    on_click=_cancel_this_run,
                    icon="stop_circle",
                    color="negative",
                ).props('size="sm" aria-label="Cancel inspected run"')

        ui.label("Jobs in Run").classes("text-sm font-semibold mt-4")
        for job in run_jobs:

            async def _inspect_child(target: JobSpec = job) -> None:
                drawer.close()
                await open_job_inspection_drawer(
                    pipeline,
                    identity,
                    target,
                    run_report=run_report,
                    all_jobs=all_jobs,
                    on_mutated=on_mutated,
                    on_filter_run=on_filter_run,
                )

            ui.button(
                f"{job.name} ({resolve_job_display_status(job)})",
                on_click=_inspect_child,
                icon="visibility",
            ).props(f'flat align="left" aria-label="Inspect job {job.id}"').classes(
                "w-full justify-start"
            )

    drawer.open()


__all__ = [
    "dispatch_lifecycle_action",
    "open_cancel_run_dialog",
    "open_job_inspection_drawer",
    "open_run_inspection_drawer",
    "render_drawer_dag_links",
    "render_drawer_explain_and_logs",
]
