"""Sortable, filterable Jobs table and CQRS lifecycle controls.

Notes/Architectural Intent:
    Renders the cluster jobs `ui.table` with WCAG AA status badges, search/status
    filtering, KPI count roll-ups, and RBAC-gated Hold/Release/Kill/Cancel Run
    commands dispatched strictly through `ExecutionPipeline`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from hexastack_auth.domain.models import Identity
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_ui.adapters.nicegui import dispatch_query
from nicegui import ui

from hexaqueue_core.domain.cqrs import ListJobsQuery
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_dashboard.adapters.ui.inspection_drawer import (
    dispatch_lifecycle_action,
    open_cancel_run_dialog,
    open_job_inspection_drawer,
)
from hexaqueue_dashboard.adapters.ui.status import (
    STATUS_BADGE_COLORS,
    TERMINAL_DISPLAY_STATES,
    resolve_job_display_status,
)
from hexaqueue_server.domain.models import RunStatusReport

JOB_TABLE_COLUMNS: list[dict[str, object]] = [
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
        "name": "updated_at",
        "label": "Updated",
        "field": "updated_at",
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


def filter_jobs(
    jobs: list[JobSpec],
    *,
    search_text: str = "",
    status_filter: str = "ALL",
) -> list[JobSpec]:
    """Filter jobs by search query and display status.

    Args:
        jobs: Source list of JobSpec instances.
        search_text: Optional case-insensitive substring matched against ID, run, name, worker.
        status_filter: Display status filter or ``ALL``.

    Returns:
        Filtered list of JobSpec instances.
    """
    needle = search_text.strip().casefold()
    target_status = status_filter.strip().upper()
    filtered: list[JobSpec] = []
    for job in jobs:
        display_status = resolve_job_display_status(job)
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


def compute_filtered_kpi_counts(
    jobs: list[JobSpec],
    *,
    search_text: str = "",
    status_filter: str = "ALL",
) -> tuple[int, int, int, bool]:
    """Compute (total, running, pending, is_filtered) counts for KPI cards.

    Args:
        jobs: Source list of JobSpec instances.
        search_text: Active search query.
        status_filter: Active status filter.

    Returns:
        Tuple of ``(total_count, running_count, pending_count, is_filtered)``.
    """
    is_filtered = bool(
        search_text.strip() or status_filter.strip().upper() not in ("", "ALL")
    )
    filtered = filter_jobs(jobs, search_text=search_text, status_filter=status_filter)
    running = sum(
        1
        for j in filtered
        if resolve_job_display_status(j) in ("RUNNING", "PROVISIONING", "CLEANUP")
    )
    pending = sum(
        1 for j in filtered if resolve_job_display_status(j) in ("PENDING", "SUBMITTED")
    )
    return len(filtered), running, pending, is_filtered


def build_job_rows(jobs: list[JobSpec]) -> list[dict[str, object]]:
    """Transform JobSpec objects into sortable ui.table row dictionaries.

    Args:
        jobs: Filtered list of JobSpec instances.

    Returns:
        List of row dictionaries for NiceGUI ``ui.table``.
    """
    rows: list[dict[str, object]] = []
    for job in jobs:
        display_status = resolve_job_display_status(job)
        is_terminal = display_status in TERMINAL_DISPLAY_STATES
        updated_str = (
            job.updated_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            if hasattr(job.updated_at, "strftime")
            else str(job.updated_at or "")
        )
        rows.append(
            {
                "job_id": job.id,
                "run_id": job.run_id,
                "name": job.name,
                "status": display_status,
                "badge_bg": STATUS_BADGE_COLORS.get(display_status, "#374151"),
                "worker_id": job.assigned_worker_id or "—",
                "updated_at": updated_str,
                "can_hold": display_status in ("PENDING", "SUBMITTED"),
                "can_release": display_status == "HELD",
                "can_cancel": not is_terminal,
            }
        )
    return rows


async def render_jobs_section(
    pipeline: ExecutionPipeline,
    identity: Identity,
    *,
    jobs: list[JobSpec] | None = None,
    runs: list[RunStatusReport] | None = None,
    on_mutated: Callable[[], Awaitable[None]] | None = None,
    on_filter_run: Callable[[str], None] | None = None,
    filter_state: dict[str, str] | None = None,
) -> None:
    """Render sortable, filterable jobs table with status badges and lifecycle controls.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
        jobs: Optional pre-fetched list of JobSpec instances.
        runs: Optional pre-fetched list of RunStatusReport instances.
        on_mutated: Optional callback invoked after a job mutation succeeds.
        on_filter_run: Optional callback to filter the jobs table to a run ID.
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

    filtered = filter_jobs(
        resolved_jobs,
        search_text=active_filters.get("search", ""),
        status_filter=active_filters.get("status", "ALL"),
    )
    rows = build_job_rows(filtered)

    table = ui.table(
        columns=JOB_TABLE_COLUMNS,
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
                    dense flat round size="sm" icon="visibility" color="primary"
                    :aria-label="'Inspect job ' + props.row.job_id"
                    @click="$parent.$emit('inspect_job', props.row)"
                >
                    <q-tooltip>Inspect job details, logs &amp; explainability</q-tooltip>
                </q-btn>
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

    jobs_by_id = {j.id: j for j in resolved_jobs}
    runs_by_id = {r.run_id: r for r in (runs or [])}

    async def _on_inspect_job(ev: object) -> None:
        args = getattr(ev, "args", {}) or {}
        target_job = jobs_by_id.get(str(args.get("job_id", "")))
        if target_job is not None:
            await open_job_inspection_drawer(
                pipeline,
                identity,
                target_job,
                run_report=runs_by_id.get(target_job.run_id),
                all_jobs=resolved_jobs,
                on_mutated=on_mutated,
                on_filter_run=on_filter_run,
            )

    async def _on_hold(ev: object) -> None:
        args = getattr(ev, "args", {}) or {}
        await dispatch_lifecycle_action(
            pipeline, identity, "hold", str(args.get("job_id", "")), on_mutated
        )

    async def _on_release(ev: object) -> None:
        args = getattr(ev, "args", {}) or {}
        await dispatch_lifecycle_action(
            pipeline, identity, "release", str(args.get("job_id", "")), on_mutated
        )

    async def _on_cancel_job(ev: object) -> None:
        args = getattr(ev, "args", {}) or {}
        await dispatch_lifecycle_action(
            pipeline, identity, "cancel_job", str(args.get("job_id", "")), on_mutated
        )

    def _on_cancel_run(ev: object) -> None:
        args = getattr(ev, "args", {}) or {}
        run_id = str(args.get("run_id", ""))
        open_cancel_run_dialog(
            run_id,
            lambda: dispatch_lifecycle_action(
                pipeline, identity, "cancel_run", run_id, on_mutated
            ),
        )

    table.on("inspect_job", _on_inspect_job)
    table.on("hold_job", _on_hold)
    table.on("release_job", _on_release)
    table.on("cancel_job", _on_cancel_job)
    table.on("cancel_run", _on_cancel_run)


__all__ = [
    "build_job_rows",
    "compute_filtered_kpi_counts",
    "filter_jobs",
    "JOB_TABLE_COLUMNS",
    "render_jobs_section",
]
