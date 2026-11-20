"""Paginated History Explorer view for searching older runs and jobs.

Notes/Architectural Intent:
    Provides dedicated historical exploration with scope switching (Jobs vs
    Runs), text/status filtering, page-by-page navigation, and unified
    inspection drawer integration routed through `ExecutionPipeline`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
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
    JOB_STATUS_FILTER_OPTIONS,
    RUN_STATUS_FILTER_OPTIONS,
    STATUS_BADGE_COLORS,
    matches_status_filter,
    resolve_job_display_status,
    resolve_run_display_status,
)
from hexaqueue_server.domain.models import RunStatusReport

HISTORY_JOB_COLUMNS: list[dict[str, object]] = [
    {"name": "job_id", "label": "Job ID", "field": "job_id", "align": "left"},
    {"name": "run_id", "label": "Run ID", "field": "run_id", "align": "left"},
    {"name": "name", "label": "Name", "field": "name", "align": "left"},
    {"name": "owner", "label": "Owner", "field": "owner", "align": "left"},
    {"name": "status", "label": "Status", "field": "status", "align": "center"},
    {"name": "updated_at", "label": "Updated", "field": "updated_at", "align": "left"},
]

HISTORY_RUN_COLUMNS: list[dict[str, object]] = [
    {"name": "run_id", "label": "Run ID", "field": "run_id", "align": "left"},
    {"name": "name", "label": "Name", "field": "name", "align": "left"},
    {"name": "owner", "label": "Owner", "field": "owner", "align": "left"},
    {"name": "status", "label": "Status", "field": "status", "align": "center"},
    {"name": "progress", "label": "Jobs", "field": "progress", "align": "center"},
    {"name": "updated_at", "label": "Updated", "field": "updated_at", "align": "left"},
]


_DURATION_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("<10s", 0.0, 10.0),
    ("10-60s", 10.0, 60.0),
    ("1-5m", 60.0, 300.0),
    ("5-15m", 300.0, 900.0),
    ("15m+", 900.0, float("inf")),
)

_OUTCOME_ORDER: tuple[tuple[str, str], ...] = (
    ("Completed", "#10b981"),
    ("Failed", "#ef4444"),
    ("Cancelled", "#f59e0b"),
    ("Timed Out", "#f97316"),
    ("Active", "#38bdf8"),
)


def _record_duration_seconds(record: RunStatusReport | JobSpec) -> float | None:
    created = getattr(record, "created_at", None)
    updated = getattr(record, "updated_at", None)
    if isinstance(created, datetime) and isinstance(updated, datetime):
        return max(0.0, (updated - created).total_seconds())
    return None


def _classify_outcome(status_text: str) -> str:
    upper = status_text.strip().upper()
    if upper in ("COMPLETED", "SUCCEEDED"):
        return "Completed"
    if upper == "FAILED":
        return "Failed"
    if upper == "CANCELLED":
        return "Cancelled"
    if upper == "TIMED_OUT":
        return "Timed Out"
    return "Active"


def compute_history_analytics(
    records: Sequence[RunStatusReport | JobSpec],
    *,
    is_runs: bool,
) -> dict[str, Any]:
    """Aggregate duration distribution and terminal outcome counts for history records.

    Args:
        records: Filtered RunStatusReport or JobSpec sequence.
        is_runs: Whether ``records`` are ``RunStatusReport`` items (vs ``JobSpec``).

    Returns:
        Dictionary containing ``total``, ``avg_duration_s``, ``p95_duration_s``,
        ``failure_rate_pct``, ``duration_buckets``, and ``outcome_counts``.

    Notes/Architectural Intent:
        Operates purely on the already-filtered historical record sequence so
        duration histograms and failure analytics remain synchronized with
        search, status, and date bounds without extra server queries.
    """
    durations: list[float] = []
    bucket_counts: dict[str, int] = {label: 0 for label, _, _ in _DURATION_BUCKETS}
    outcome_counts: dict[str, int] = {name: 0 for name, _ in _OUTCOME_ORDER}

    for rec in records:
        dur = _record_duration_seconds(rec)
        if dur is not None:
            durations.append(dur)
            for label, low, high in _DURATION_BUCKETS:
                if low <= dur < high:
                    bucket_counts[label] += 1
                    break
        status_str = (
            resolve_run_display_status(rec)
            if isinstance(rec, RunStatusReport)
            else resolve_job_display_status(rec)
        )
        outcome_counts[_classify_outcome(status_str)] += 1

    durations.sort()
    avg_dur = (sum(durations) / len(durations)) if durations else 0.0
    p95_idx = min(len(durations) - 1, int(0.95 * len(durations))) if durations else 0
    p95_dur = durations[p95_idx] if durations else 0.0
    terminal_total = (
        outcome_counts["Completed"]
        + outcome_counts["Failed"]
        + outcome_counts["Cancelled"]
        + outcome_counts["Timed Out"]
    )
    failure_total = outcome_counts["Failed"] + outcome_counts["Timed Out"]
    failure_rate = (failure_total / terminal_total * 100.0) if terminal_total else 0.0

    return {
        "total": len(records),
        "avg_duration_s": round(avg_dur, 1),
        "p95_duration_s": round(p95_dur, 1),
        "failure_rate_pct": round(failure_rate, 1),
        "duration_buckets": [
            (label, bucket_counts[label]) for label, _, _ in _DURATION_BUCKETS
        ],
        "outcome_counts": outcome_counts,
    }


def build_history_duration_histogram_svg(
    bucket_counts: list[tuple[str, int]],
) -> str:
    """Build an accessible inline SVG duration histogram for historical records.

    Args:
        bucket_counts: Ordered ``(bucket_label, count)`` pairs.

    Returns:
        Inline SVG markup string with WCAG 2.1 AA contrast and ARIA label.
    """
    max_count = max((count for _, count in bucket_counts), default=1) or 1
    bars: list[str] = []
    width, height = 340, 118
    plot_top, plot_h = 22, 68
    slot_w = (width - 28) / max(1, len(bucket_counts))
    bar_w = max(24.0, slot_w - 14.0)

    for idx, (label, count) in enumerate(bucket_counts):
        x = 14.0 + idx * slot_w + (slot_w - bar_w) / 2.0
        bar_h = (count / max_count) * plot_h if count > 0 else 2.0
        y = plot_top + plot_h - bar_h
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
            f'height="{bar_h:.1f}" rx="3" fill="#38bdf8"/>'
            f'<text x="{x + bar_w / 2.0:.1f}" y="{y - 4:.1f}" '
            'text-anchor="middle" fill="#f8fafc" font-size="10" '
            f'font-family="monospace">{count}</text>'
            f'<text x="{x + bar_w / 2.0:.1f}" y="{height - 10}" '
            'text-anchor="middle" fill="#cbd5e1" font-size="10" '
            f'font-family="monospace">{label}</text>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        'role="img" aria-label="Duration distribution histogram" '
        'style="width:100%;height:auto;background:#0f172a;border-radius:6px;">'
        "<title>Duration distribution histogram</title>"
        '<text x="12" y="15" fill="#f8fafc" font-size="11" font-weight="600" '
        'font-family="sans-serif">Duration Distribution</text>'
        f"{''.join(bars)}"
        "</svg>"
    )


def build_history_outcome_svg(outcome_counts: dict[str, int]) -> str:
    """Build an accessible inline SVG outcome & failure breakdown bar chart.

    Args:
        outcome_counts: Mapping of outcome label to record count.

    Returns:
        Inline SVG markup string with WCAG 2.1 AA contrast and ARIA label.
    """
    max_count = max(outcome_counts.values(), default=1) or 1
    width, height = 340, 118
    rows_svg: list[str] = []
    bar_max_w = 175.0
    for idx, (label, color) in enumerate(_OUTCOME_ORDER):
        count = outcome_counts.get(label, 0)
        y = 26 + idx * 17
        bar_w = (count / max_count) * bar_max_w if count > 0 else 2.0
        rows_svg.append(
            f'<text x="12" y="{y + 9}" fill="#e2e8f0" font-size="10" '
            f'font-family="sans-serif">{label}</text>'
            f'<rect x="92" y="{y}" width="{bar_w:.1f}" height="10" rx="2" fill="{color}"/>'
            f'<text x="{92 + bar_w + 6:.1f}" y="{y + 9}" fill="#f8fafc" '
            f'font-size="10" font-family="monospace">{count}</text>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        'role="img" aria-label="Outcome and failure breakdown chart" '
        'style="width:100%;height:auto;background:#0f172a;border-radius:6px;">'
        "<title>Outcome and failure breakdown chart</title>"
        '<text x="12" y="15" fill="#f8fafc" font-size="11" font-weight="600" '
        'font-family="sans-serif">Outcome Breakdown</text>'
        f"{''.join(rows_svg)}"
        "</svg>"
    )


def _render_history_analytics(
    records: Sequence[RunStatusReport | JobSpec],
    *,
    is_runs: bool,
) -> None:
    analytics = compute_history_analytics(records, is_runs=is_runs)
    dur_svg = build_history_duration_histogram_svg(analytics["duration_buckets"])
    out_svg = build_history_outcome_svg(analytics["outcome_counts"])
    summary_text = (
        f"Filtered: {analytics['total']} | "
        f"Avg Duration: {analytics['avg_duration_s']:.1f}s | "
        f"P95: {analytics['p95_duration_s']:.1f}s | "
        f"Failure Rate: {analytics['failure_rate_pct']:.1f}%"
    )
    with ui.card().classes("w-full p-3 mt-2 bg-slate-900"):
        ui.label(summary_text).classes("text-xs font-mono text-slate-200 mb-2")
        ui.html(
            '<div class="grid grid-cols-1 md:grid-cols-2 gap-3 w-full">'
            f"{dur_svg}{out_svg}"
            "</div>",
            sanitize=False,
        )


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
        if not matches_status_filter(run_status, target_status):
            continue
        if not _within_date_bounds(run.updated_at, date_from, date_to):
            continue
        if (
            needle
            and needle not in f"{run.run_id} {run.name or ''} {run.owner}".casefold()
        ):
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
                "owner": run.owner,
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
    _render_history_analytics(filtered_runs, is_runs=True)
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
    _render_history_analytics(filtered_jobs, is_runs=False)
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


def _render_history_controls(
    history_state: HistoryUIState,
    on_scope_change: Callable[[str], None],
    on_filter_change: Callable[[], None],
) -> None:
    """Render scope toggles, search, status, and date filter controls."""

    def _bind_str_field(attr: str, default: str = "") -> Callable[[object], None]:
        def _handler(ev: object) -> None:
            val = str(getattr(ev, "value", default) or default)
            if val != getattr(history_state, attr):
                setattr(history_state, attr, val)
                history_state.page = 1
                on_filter_change()

        return _handler

    with ui.row().classes("w-full items-center flex-wrap gap-3 mt-2"):
        ui.button(
            "Jobs History",
            on_click=lambda: on_scope_change("jobs"),
            color="primary" if history_state.kind == "jobs" else "grey-8",
        ).props('size="sm" aria-label="Explore jobs history"')
        ui.button(
            "Runs History",
            on_click=lambda: on_scope_change("runs"),
            color="primary" if history_state.kind == "runs" else "grey-8",
        ).props('size="sm" aria-label="Explore runs history"')

        ui.input(
            label="History Search",
            value=history_state.search,
            placeholder="Search historical ID, run, name...",
            on_change=_bind_str_field("search"),
        ).props('clearable aria-label="Search historical jobs and runs"').classes(
            "w-72"
        )

        status_opts = (
            RUN_STATUS_FILTER_OPTIONS
            if history_state.kind == "runs"
            else JOB_STATUS_FILTER_OPTIONS
        )
        if history_state.status not in status_opts:
            history_state.status = "ALL"
        ui.select(
            options=status_opts,
            value=history_state.status,
            label="History Status",
            on_change=_bind_str_field("status", "ALL"),
        ).props('aria-label="Filter history by status"').classes("w-56")

        ui.input(
            label="From Date",
            value=history_state.date_from,
            on_change=_bind_str_field("date_from"),
        ).props('type="date" clearable aria-label="History start date"').classes("w-40")
        ui.input(
            label="To Date",
            value=history_state.date_to,
            on_change=_bind_str_field("date_to"),
        ).props('type="date" clearable aria-label="History end date"').classes("w-40")


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

    def _set_scope(kind: str) -> None:
        history_state.kind = kind
        history_state.page = 1
        _trigger_refresh()

    _render_history_controls(history_state, _set_scope, lambda: _render_results())
    results_box = ui.column().classes("w-full")

    def _render_results() -> None:
        results_box.clear()
        with results_box:
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
                            _render_results()

                    def _next_page() -> None:
                        if history_state.page < total_pages:
                            history_state.page += 1
                            _render_results()

                    ui.button(
                        "Previous", on_click=_prev_page, icon="chevron_left"
                    ).props(
                        'size="sm" color="primary" aria-label="Previous history page"'
                    )
                    ui.button("Next", on_click=_next_page, icon="chevron_right").props(
                        'size="sm" color="primary" aria-label="Next history page"'
                    )

    _render_results()


__all__ = [
    "build_history_duration_histogram_svg",
    "build_history_outcome_svg",
    "build_history_run_rows",
    "compute_history_analytics",
    "filter_history_runs",
    "HISTORY_JOB_COLUMNS",
    "HISTORY_RUN_COLUMNS",
    "paginate_history_items",
    "render_history_section",
]
