"""Paginated History Explorer view for searching older runs and jobs.

Notes/Architectural Intent:
    Provides dedicated historical exploration with scope switching (Jobs vs
    Runs), text/status filtering, page-by-page navigation, and unified
    inspection drawer integration routed through `ExecutionPipeline`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from hexastack_auth.domain.models import Identity
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from nicegui import ui

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_dashboard.adapters.ui.inspection_drawer import (
    open_job_inspection_drawer,
    open_run_inspection_drawer,
)
from hexaqueue_dashboard.adapters.ui.jobs_table import build_job_rows, filter_jobs
from hexaqueue_dashboard.adapters.ui.state import DrawerUIState, HistoryUIState
from hexaqueue_dashboard.adapters.ui.status import (
    STATUS_BADGE_COLORS,
    resolve_run_display_status,
)
from hexaqueue_server.domain.models import RunStatusReport

HISTORY_JOB_COLUMNS: list[dict[str, object]] = [
    {"name": "job_id", "label": "Job ID", "field": "job_id", "align": "left"},
    {"name": "run_id", "label": "Run ID", "field": "run_id", "align": "left"},
    {"name": "name", "label": "Name", "field": "name", "align": "left"},
    {"name": "status", "label": "Status", "field": "status", "align": "center"},
    {"name": "updated_at", "label": "Updated", "field": "updated_at", "align": "left"},
]

HISTORY_RUN_COLUMNS: list[dict[str, object]] = [
    {"name": "run_id", "label": "Run ID", "field": "run_id", "align": "left"},
    {"name": "name", "label": "Name", "field": "name", "align": "left"},
    {"name": "status", "label": "Status", "field": "status", "align": "center"},
    {"name": "progress", "label": "Jobs", "field": "progress", "align": "center"},
    {"name": "updated_at", "label": "Updated", "field": "updated_at", "align": "left"},
]


def paginate_history_items[T](
    items: list[T],
    page: int,
    page_size: int,
) -> tuple[list[T], int, int]:
    """Return a single page slice, total pages, and clamped 1-based page index.

    Args:
        items: Full filtered sequence of items.
        page: Requested 1-based page number.
        page_size: Maximum items per page.

    Returns:
        Tuple of ``(page_items, total_pages, clamped_page)``.
    """
    safe_size = max(1, page_size)
    total_pages = max(1, (len(items) + safe_size - 1) // safe_size)
    clamped = max(1, min(page, total_pages))
    start = (clamped - 1) * safe_size
    return items[start : start + safe_size], total_pages, clamped


def _within_date_bounds(ts: Any, date_from: str, date_to: str) -> bool:
    if not date_from and not date_to:
        return True
    day_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts or "")[:10]
    if date_from and day_str < date_from:
        return False
    return not (date_to and day_str > date_to)


def filter_history_runs(
    runs: list[RunStatusReport],
    *,
    search_text: str = "",
    status_filter: str = "ALL",
    date_from: str = "",
    date_to: str = "",
) -> list[RunStatusReport]:
    """Filter RunStatusReport records by substring search, status, and date range.

    Args:
        runs: Source RunStatusReport list.
        search_text: Case-insensitive substring matched against run ID or name.
        status_filter: Target run display status or ``ALL``.
        date_from: Optional inclusive start date (``YYYY-MM-DD``).
        date_to: Optional inclusive end date (``YYYY-MM-DD``).

    Returns:
        Filtered list of RunStatusReport instances sorted newest-first.
    """
    needle = search_text.strip().casefold()
    target_status = status_filter.strip().upper()
    matched: list[RunStatusReport] = []
    for run in runs:
        run_status = resolve_run_display_status(run)
        if target_status not in ("", "ALL") and run_status != target_status:
            continue
        if not _within_date_bounds(run.updated_at, date_from, date_to):
            continue
        if needle and needle not in f"{run.run_id} {run.name or ''}".casefold():
            continue
        matched.append(run)
    return sorted(matched, key=lambda r: str(r.updated_at or ""), reverse=True)


def build_history_run_rows(runs: list[RunStatusReport]) -> list[dict[str, object]]:
    """Transform RunStatusReport records into History Explorer table rows.

    Args:
        runs: Filtered and paginated RunStatusReport list.

    Returns:
        List of row dictionaries for NiceGUI ``ui.table``.
    """
    rows: list[dict[str, object]] = []
    for run in runs:
        run_status = resolve_run_display_status(run)
        updated_str = (
            run.updated_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            if hasattr(run.updated_at, "strftime")
            else str(run.updated_at or "")
        )
        rows.append(
            {
                "run_id": run.run_id,
                "name": run.name or run.run_id,
                "status": run_status,
                "badge_bg": STATUS_BADGE_COLORS.get(run_status, "#374151"),
                "progress": f"{run.completed_jobs}/{run.total_jobs}",
                "updated_at": updated_str,
            }
        )
    return rows


def _extract_clicked_row(ev: object) -> dict[str, Any]:
    args = getattr(ev, "args", None)
    if isinstance(args, list) and len(args) >= 2 and isinstance(args[1], dict):
        return args[1]
    return args if isinstance(args, dict) else {}


_STATUS_BADGE_SLOT = """
        <q-td :props="props">
            <q-badge
                :style="{ backgroundColor: props.row.badge_bg, color: '#ffffff', fontWeight: 700 }"
                class="px-2 py-1 text-xs rounded"
            >
                {{ props.value }}
            </q-badge>
        </q-td>
        """


def _render_history_runs_table(
    pipeline: ExecutionPipeline,
    identity: Identity,
    runs: list[RunStatusReport],
    jobs: list[JobSpec],
    history_state: HistoryUIState,
    drawer_state: DrawerUIState | None,
    *,
    on_mutated: Callable[[], Awaitable[None]] | None,
    on_filter_run: Callable[[str], None] | None,
) -> tuple[int, int, int]:
    filtered_runs = filter_history_runs(
        runs,
        search_text=history_state.search,
        status_filter=history_state.status,
        date_from=history_state.date_from,
        date_to=history_state.date_to,
    )
    page_runs, total_pages, clamped_page = paginate_history_items(
        filtered_runs, history_state.page, history_state.page_size
    )
    history_state.page = clamped_page
    table = ui.table(
        columns=HISTORY_RUN_COLUMNS,
        rows=build_history_run_rows(page_runs),
        row_key="run_id",
    ).classes("w-full mt-2")
    table.add_slot("body-cell-status", _STATUS_BADGE_SLOT)
    runs_by_id = {r.run_id: r for r in runs}

    async def _on_run_click(ev: object) -> None:
        row = _extract_clicked_row(ev)
        run_report = runs_by_id.get(str(row.get("run_id", "")))
        if run_report is not None:
            await open_run_inspection_drawer(
                pipeline,
                identity,
                run_report,
                jobs,
                on_mutated=on_mutated,
                on_filter_run=on_filter_run,
                drawer_state=drawer_state,
            )

    table.on("rowClick", _on_run_click)
    return len(filtered_runs), total_pages, clamped_page


def _render_history_jobs_table(
    pipeline: ExecutionPipeline,
    identity: Identity,
    runs: list[RunStatusReport],
    jobs: list[JobSpec],
    history_state: HistoryUIState,
    drawer_state: DrawerUIState | None,
    *,
    on_mutated: Callable[[], Awaitable[None]] | None,
    on_filter_run: Callable[[str], None] | None,
) -> tuple[int, int, int]:
    filtered_jobs = sorted(
        [
            j
            for j in filter_jobs(
                jobs,
                search_text=history_state.search,
                status_filter=history_state.status,
            )
            if _within_date_bounds(
                j.updated_at, history_state.date_from, history_state.date_to
            )
        ],
        key=lambda j: str(j.updated_at or ""),
        reverse=True,
    )
    page_jobs, total_pages, clamped_page = paginate_history_items(
        filtered_jobs, history_state.page, history_state.page_size
    )
    history_state.page = clamped_page
    table = ui.table(
        columns=HISTORY_JOB_COLUMNS,
        rows=build_job_rows(page_jobs),
        row_key="job_id",
    ).classes("w-full mt-2")
    table.add_slot("body-cell-status", _STATUS_BADGE_SLOT)
    jobs_by_id = {j.id: j for j in jobs}
    runs_by_id = {r.run_id: r for r in runs}

    async def _on_job_click(ev: object) -> None:
        row = _extract_clicked_row(ev)
        job = jobs_by_id.get(str(row.get("job_id", "")))
        if job is not None:
            await open_job_inspection_drawer(
                pipeline,
                identity,
                job,
                run_report=runs_by_id.get(job.run_id),
                all_jobs=jobs,
                on_mutated=on_mutated,
                on_filter_run=on_filter_run,
                drawer_state=drawer_state,
            )

    table.on("rowClick", _on_job_click)
    return len(filtered_jobs), total_pages, clamped_page


def render_history_section(
    pipeline: ExecutionPipeline,
    identity: Identity,
    runs: list[RunStatusReport],
    jobs: list[JobSpec],
    history_state: HistoryUIState,
    drawer_state: DrawerUIState | None = None,
    *,
    on_mutated: Callable[[], Awaitable[None]] | None = None,
    on_filter_run: Callable[[str], None] | None = None,
    on_refresh: Callable[[], None] | None = None,
) -> None:
    """Render paginated History Explorer for older runs and jobs.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
        runs: Available RunStatusReport history.
        jobs: Available JobSpec history.
        history_state: HistoryUIState holding scope, search, status, and page.
        drawer_state: Optional DrawerUIState for opening inspection drawers.
        on_mutated: Optional async callback invoked after lifecycle mutations.
        on_filter_run: Optional callback to filter the jobs table to a run ID.
        on_refresh: Optional callback to trigger UI refresh on pagination/filter.
    """
    ui.label("History Explorer").classes("text-lg font-semibold mt-4")

    def _trigger_refresh() -> None:
        if on_refresh is not None:
            on_refresh()

    with ui.row().classes("w-full items-center flex-wrap gap-3 mt-2"):
        ui.button(
            "Jobs History",
            on_click=lambda: _set_scope("jobs"),
            color="primary" if history_state.kind == "jobs" else "grey-8",
        ).props('size="sm" aria-label="Explore jobs history"')
        ui.button(
            "Runs History",
            on_click=lambda: _set_scope("runs"),
            color="primary" if history_state.kind == "runs" else "grey-8",
        ).props('size="sm" aria-label="Explore runs history"')

        def _set_scope(kind: str) -> None:
            history_state.kind = kind
            history_state.page = 1
            _trigger_refresh()

        def _on_search(ev: object) -> None:
            val = str(getattr(ev, "value", "") or "")
            if val != history_state.search:
                history_state.search = val
                history_state.page = 1
                _trigger_refresh()

        def _on_status(ev: object) -> None:
            val = str(getattr(ev, "value", "ALL") or "ALL")
            if val != history_state.status:
                history_state.status = val
                history_state.page = 1
                _trigger_refresh()

        ui.input(
            label="History Search",
            value=history_state.search,
            placeholder="Search historical ID, run, name...",
            on_change=_on_search,
        ).props('clearable aria-label="Search historical jobs and runs"').classes(
            "w-72"
        )

        status_opts = (
            [
                "ALL",
                "PENDING",
                "IN_PROGRESS",
                "RUNNING",
                "SUCCEEDED",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
            ]
            if history_state.kind == "runs"
            else [
                "ALL",
                "PENDING",
                "RUNNING",
                "HELD",
                "BLOCKED",
                "SUCCEEDED",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
            ]
        )
        if history_state.status not in status_opts:
            history_state.status = "ALL"
        ui.select(
            options=status_opts,
            value=history_state.status,
            label="History Status",
            on_change=_on_status,
        ).props('aria-label="Filter history by status"').classes("w-44")

        def _on_date_from(ev: object) -> None:
            val = str(getattr(ev, "value", "") or "")
            if val != history_state.date_from:
                history_state.date_from = val
                history_state.page = 1
                _trigger_refresh()

        def _on_date_to(ev: object) -> None:
            val = str(getattr(ev, "value", "") or "")
            if val != history_state.date_to:
                history_state.date_to = val
                history_state.page = 1
                _trigger_refresh()

        ui.input(
            label="From Date",
            value=history_state.date_from,
            on_change=_on_date_from,
        ).props('type="date" clearable aria-label="History start date"').classes("w-40")
        ui.input(
            label="To Date",
            value=history_state.date_to,
            on_change=_on_date_to,
        ).props('type="date" clearable aria-label="History end date"').classes("w-40")

    if history_state.kind == "runs":
        total_count, total_pages, clamped_page = _render_history_runs_table(
            pipeline,
            identity,
            runs,
            jobs,
            history_state,
            drawer_state,
            on_mutated=on_mutated,
            on_filter_run=on_filter_run,
        )
    else:
        total_count, total_pages, clamped_page = _render_history_jobs_table(
            pipeline,
            identity,
            runs,
            jobs,
            history_state,
            drawer_state,
            on_mutated=on_mutated,
            on_filter_run=on_filter_run,
        )

    with ui.row().classes("w-full items-center justify-between mt-3"):
        ui.label(
            f"Page {clamped_page} of {total_pages} ({total_count} matching records)"
        ).classes("text-xs text-slate-300")
        with ui.row().classes("gap-2"):

            def _prev_page() -> None:
                if history_state.page > 1:
                    history_state.page -= 1
                    _trigger_refresh()

            def _next_page() -> None:
                if history_state.page < total_pages:
                    history_state.page += 1
                    _trigger_refresh()

            ui.button("Previous", on_click=_prev_page, icon="chevron_left").props(
                'size="sm" color="primary" aria-label="Previous history page"'
            )
            ui.button("Next", on_click=_next_page, icon="chevron_right").props(
                'size="sm" color="primary" aria-label="Next history page"'
            )


__all__ = [
    "build_history_run_rows",
    "filter_history_runs",
    "HISTORY_JOB_COLUMNS",
    "HISTORY_RUN_COLUMNS",
    "paginate_history_items",
    "render_history_section",
]
