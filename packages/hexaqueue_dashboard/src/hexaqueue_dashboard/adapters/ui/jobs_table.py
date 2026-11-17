"""Sortable, filterable Jobs table and CQRS lifecycle controls.

Notes/Architectural Intent:
    Renders the cluster jobs `ui.table` with WCAG AA status badges, search/status
    filtering, KPI count roll-ups, and RBAC-gated Hold/Release/Kill/Cancel Run
    commands dispatched strictly through `ExecutionPipeline`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

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
from hexaqueue_dashboard.adapters.ui.state import (
    DrawerUIState,
    FilterUIState,
    JobsTableUIState,
)
from hexaqueue_dashboard.adapters.ui.status import (
    STATUS_BADGE_COLORS,
    TERMINAL_DISPLAY_STATES,
    matches_status_filter,
    resolve_job_display_status,
    status_sort_rank,
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
        "name": "owner",
        "label": "Owner",
        "field": "owner",
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
        if not matches_status_filter(display_status, target_status):
            continue
        if needle:
            haystack = (
                f"{job.id} {job.run_id} {job.name} {job.owner} {job.assigned_worker_id or ''}"
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
                "owner": job.owner,
                "status": display_status,
                "status_rank": status_sort_rank(display_status),
                "badge_bg": STATUS_BADGE_COLORS.get(display_status, "#374151"),
                "worker_id": job.assigned_worker_id or "—",
                "updated_at": updated_str,
                "can_hold": display_status in ("PENDING", "SUBMITTED"),
                "can_release": display_status == "HELD",
                "can_cancel": not is_terminal,
            }
        )
    return rows


def sort_job_rows(
    rows: list[dict[str, object]],
    sort_by: str | None,
    descending: bool = False,
) -> list[dict[str, object]]:
    """Sort job row dictionaries in Python, using semantic rank for ``status``.

    Args:
        rows: List of row dictionaries produced by ``build_job_rows``.
        sort_by: Column key to sort by, or None to preserve order.
        descending: Whether to reverse the sort order.

    Returns:
        Sorted list of row dictionaries.

    Notes/Architectural Intent:
        Replaces client-side Quasar JS sorting (which can be overridden by
        NiceGUI's table wrapper) so ``Status`` reliably sorts by
        ``status_rank`` across initial render, click, and SSE refreshes.
    """
    if not sort_by:
        return list(rows)
    if sort_by == "status":
        return sorted(
            rows,
            key=lambda r: (
                rank if isinstance(rank := r.get("status_rank", 99), int) else 99,
                str(r.get("job_id", "")),
            ),
            reverse=descending,
        )
    return sorted(
        rows,
        key=lambda r: str(r.get(sort_by, "")).casefold(),
        reverse=descending,
    )


_NOOP_SORT_PROP = ':sort-method="(rows) => rows"'


def _apply_pagination_update(
    table: Any,
    resolved_pagination: dict[str, Any] | None,
    ev: object,
) -> None:
    """Persist pagination state and re-sort table rows in Python on header click."""
    args = getattr(ev, "args", None)
    if not isinstance(args, dict):
        return
    if resolved_pagination is not None:
        resolved_pagination.update(args)
    sort_by = args.get("sortBy")
    desc = bool(args.get("descending", False))
    current_rows = list(getattr(table, "rows", []))
    if current_rows and hasattr(table, "rows"):
        table.rows[:] = sort_job_rows(
            current_rows, str(sort_by) if sort_by else None, desc
        )
    if hasattr(table, "pagination"):
        table.pagination = dict(args)
    if hasattr(table, "update"):
        table.update()


def _wire_jobs_table_events(
    table: Any,
    pipeline: ExecutionPipeline,
    identity: Identity,
    resolved_jobs: list[JobSpec],
    runs: list[RunStatusReport] | None,
    *,
    on_mutated: Callable[[], Awaitable[None]] | None,
    on_filter_run: Callable[[str], None] | None,
    resolved_pagination: dict[str, Any] | None,
    resolved_host: Any,
    drawer_state: DrawerUIState | None,
) -> None:
    """Attach row-click, inspection, pagination, and lifecycle handlers to `ui.table`."""
    jobs_by_id = {j.id: j for j in resolved_jobs}
    runs_by_id = {r.run_id: r for r in (runs or [])}

    async def _inspect_row(row_data: dict[str, Any]) -> None:
        target_job = jobs_by_id.get(str(row_data.get("job_id", "")))
        if target_job is not None:
            await open_job_inspection_drawer(
                pipeline,
                identity,
                target_job,
                run_report=runs_by_id.get(target_job.run_id),
                all_jobs=resolved_jobs,
                on_mutated=on_mutated,
                on_filter_run=on_filter_run,
                drawer_host=resolved_host,
                drawer_state=drawer_state,
            )

    async def _on_inspect_job(ev: object) -> None:
        args = getattr(ev, "args", {}) or {}
        if isinstance(args, dict):
            await _inspect_row(args)

    async def _on_row_click(ev: object) -> None:
        args = getattr(ev, "args", None)
        if isinstance(args, list) and len(args) >= 2 and isinstance(args[1], dict):
            await _inspect_row(args[1])
        elif isinstance(args, dict):
            await _inspect_row(args)

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

    table.on(
        "update:pagination",
        lambda ev: _apply_pagination_update(table, resolved_pagination, ev),
    )
    table.on("inspect_job", _on_inspect_job)
    table.on("rowClick", _on_row_click)
    table.on("hold_job", _on_hold)
    table.on("release_job", _on_release)
    table.on("cancel_job", _on_cancel_job)
    table.on("cancel_run", _on_cancel_run)


async def render_jobs_section(
    pipeline: ExecutionPipeline,
    identity: Identity,
    *,
    jobs: list[JobSpec] | None = None,
    runs: list[RunStatusReport] | None = None,
    on_mutated: Callable[[], Awaitable[None]] | None = None,
    on_filter_run: Callable[[str], None] | None = None,
    on_refresh: Callable[[], None] | None = None,
    show_heading: bool = True,
    filter_state: dict[str, str] | None = None,
    pagination_state: dict[str, Any] | None = None,
    drawer_host: Any = None,
    filters: FilterUIState | None = None,
    table_state: JobsTableUIState | None = None,
    drawer_state: DrawerUIState | None = None,
) -> None:
    """Render sortable, filterable jobs table with status badges and lifecycle controls.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
        jobs: Optional pre-fetched list of JobSpec instances.
        runs: Optional pre-fetched list of RunStatusReport instances.
        on_mutated: Optional callback invoked after a job mutation succeeds.
        on_filter_run: Optional callback to filter the jobs table to a run ID.
        on_refresh: Optional callback to refresh the view when loading more rows.
        show_heading: Whether to render the section heading above the table.
        filter_state: Optional mutable dict persisting search/status filter values.
        pagination_state: Optional mutable dict persisting sort/page state across refreshes.
        drawer_host: Optional persistent NiceGUI container for slide-over drawers.
        filters: Optional component-scoped FilterUIState.
        table_state: Optional component-scoped JobsTableUIState.
        drawer_state: Optional component-scoped DrawerUIState.
    """
    resolved_filter = (
        filters.as_dict()
        if filters is not None
        else (filter_state or {"search": "", "status": "ALL"})
    )
    resolved_pagination = (
        table_state.pagination if table_state is not None else pagination_state
    )
    resolved_host = drawer_state.host if drawer_state is not None else drawer_host
    is_admin = "admin" in identity.roles
    resolved_jobs: list[JobSpec] = (
        jobs
        if jobs is not None
        else await dispatch_query(
            pipeline,
            ListJobsQuery(user_id=identity.user_id, elevate=is_admin),
        )
    )
    active_filters = resolved_filter
    if show_heading:
        ui.label("Jobs").classes("text-lg font-semibold mt-4")
    if not resolved_jobs:
        ui.label("No jobs in queue.").classes("text-slate-400")
        return

    filtered = filter_jobs(
        resolved_jobs,
        search_text=active_filters.get("search", ""),
        status_filter=active_filters.get("status", "ALL"),
    )
    window_limit = (
        table_state.history_limit if table_state is not None else len(filtered)
    )
    active_pagination = (
        resolved_pagination
        if resolved_pagination is not None
        else {"rowsPerPage": 15, "sortBy": "updated_at", "descending": True}
    )
    sort_col = active_pagination.get("sortBy")
    all_rows = sort_job_rows(
        build_job_rows(filtered),
        str(sort_col) if sort_col else "updated_at",
        bool(active_pagination.get("descending", True)) if sort_col else True,
    )
    rows = all_rows[:window_limit]

    table = (
        ui.table(
            columns=JOB_TABLE_COLUMNS,
            rows=rows,
            row_key="job_id",
            pagination=dict(active_pagination),
        )
        .classes("w-full mt-2")
        .props(_NOOP_SORT_PROP)
    )

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
                    @click.stop="$parent.$emit('inspect_job', props.row)"
                >
                    <q-tooltip>Inspect job details, logs &amp; explainability</q-tooltip>
                </q-btn>
                <q-btn
                    v-if="props.row.can_hold"
                    dense flat round size="sm" icon="pause_circle" color="purple-8"
                    :aria-label="'Hold job ' + props.row.job_id"
                    @click.stop="$parent.$emit('hold_job', props.row)"
                >
                    <q-tooltip>Hold job</q-tooltip>
                </q-btn>
                <q-btn
                    v-if="props.row.can_release"
                    dense flat round size="sm" icon="play_circle" color="green-8"
                    :aria-label="'Release job ' + props.row.job_id"
                    @click.stop="$parent.$emit('release_job', props.row)"
                >
                    <q-tooltip>Release job</q-tooltip>
                </q-btn>
                <q-btn
                    v-if="props.row.can_cancel"
                    dense flat round size="sm" icon="cancel" color="red-8"
                    :aria-label="'Kill job ' + props.row.job_id"
                    @click.stop="$parent.$emit('cancel_job', props.row)"
                >
                    <q-tooltip>Kill job</q-tooltip>
                </q-btn>
                <q-btn
                    v-if="props.row.can_cancel"
                    dense flat round size="sm" icon="stop_circle" color="grey-8"
                    :aria-label="'Cancel run ' + props.row.run_id"
                    @click.stop="$parent.$emit('cancel_run', props.row)"
                >
                    <q-tooltip>Cancel run</q-tooltip>
                </q-btn>
            </div>
        </q-td>
        """,
    )

    _wire_jobs_table_events(
        table,
        pipeline,
        identity,
        resolved_jobs,
        runs,
        on_mutated=on_mutated,
        on_filter_run=on_filter_run,
        resolved_pagination=resolved_pagination,
        resolved_host=resolved_host,
        drawer_state=drawer_state,
    )
    if table_state is not None and len(all_rows) > len(rows):

        def _load_more_jobs() -> None:
            table_state.history_limit += 50
            if on_refresh is not None:
                on_refresh()

        ui.button(
            f"Load More Jobs (+50) — showing {len(rows)} of {len(all_rows)}",
            on_click=_load_more_jobs,
            icon="expand_more",
        ).props('size="sm" color="primary" aria-label="Load more jobs"').classes("mt-2")


__all__ = [
    "build_job_rows",
    "compute_filtered_kpi_counts",
    "filter_jobs",
    "JOB_TABLE_COLUMNS",
    "render_jobs_section",
    "sort_job_rows",
]
