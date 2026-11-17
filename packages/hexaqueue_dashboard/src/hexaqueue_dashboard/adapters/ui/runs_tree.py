"""Expandable Runs & nested hexaflow DAG tree view.

Notes/Architectural Intent:
    Builds hierarchical `ui.tree` nodes from `RunStatusReport.dependencies`
    and leaf `JobSpec` records, wiring selection directly into the unified
    inspection drawer without deep page navigation.
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
from hexaqueue_dashboard.adapters.ui.status import (
    STATUS_BADGE_COLORS,
    resolve_job_display_status,
    resolve_run_display_status,
)
from hexaqueue_server.domain.models import RunStatusReport


def build_dag_job_subtree(
    job: JobSpec,
    jobs_by_id: dict[str, JobSpec],
    children_map: dict[str, list[str]],
    visited: set[str],
) -> dict[str, object]:
    """Build a nested tree node for a job and its downstream DAG dependents.

    Args:
        job: Root or intermediate JobSpec node.
        jobs_by_id: Mapping of job_id -> JobSpec for the run.
        children_map: Adjacency mapping of parent_job_id -> child_job_ids.
        visited: Cycle-guard set of visited job IDs.

    Returns:
        NiceGUI ``ui.tree`` node dictionary.
    """
    visited.add(job.id)
    display_status = resolve_job_display_status(job)
    worker_suffix = f" · {job.assigned_worker_id}" if job.assigned_worker_id else ""
    node: dict[str, object] = {
        "id": f"job:{job.id}",
        "label": f"{job.name} ({job.id}){worker_suffix}",
        "status": display_status,
        "badge_bg": STATUS_BADGE_COLORS.get(display_status, "#374151"),
        "kind": "job",
        "job_id": job.id,
        "run_id": job.run_id,
    }
    child_nodes: list[dict[str, object]] = []
    for child_id in children_map.get(job.id, []):
        if child_id not in visited and child_id in jobs_by_id:
            child_nodes.append(
                build_dag_job_subtree(
                    jobs_by_id[child_id], jobs_by_id, children_map, visited
                )
            )
    if child_nodes:
        node["children"] = child_nodes
    return node


def build_single_run_tree_node(
    run: RunStatusReport,
    run_jobs: list[JobSpec],
) -> dict[str, object]:
    """Build a single Run tree node with its nested DAG job children.

    Args:
        run: Aggregated RunStatusReport.
        run_jobs: Jobs belonging to ``run``.

    Returns:
        NiceGUI ``ui.tree`` root node dictionary.
    """
    run_status = resolve_run_display_status(run)
    jobs_by_id = {j.id: j for j in run_jobs}
    children_map: dict[str, list[str]] = {}
    for child_id, parents in run.dependencies.items():
        for parent_id in parents:
            children_map.setdefault(parent_id, []).append(child_id)

    root_jobs = [j for j in run_jobs if not run.dependencies.get(j.id)] or run_jobs
    visited: set[str] = set()
    job_children = [
        build_dag_job_subtree(job, jobs_by_id, children_map, visited)
        for job in root_jobs
    ]
    for job in run_jobs:
        if job.id not in visited:
            job_children.append(
                build_dag_job_subtree(job, jobs_by_id, children_map, visited)
            )

    run_label = f"{run.name or run.run_id} — {run.completed_jobs}/{run.total_jobs} jobs"
    return {
        "id": f"run:{run.run_id}",
        "label": run_label,
        "status": run_status,
        "badge_bg": STATUS_BADGE_COLORS.get(run_status, "#374151"),
        "kind": "run",
        "run_id": run.run_id,
        "children": job_children,
    }


def build_run_tree_nodes(
    runs: list[RunStatusReport],
    jobs: list[JobSpec],
    *,
    search_text: str = "",
    status_filter: str = "ALL",
) -> list[dict[str, object]]:
    """Build hierarchical ui.tree nodes for runs and nested hexaflow DAG jobs.

    Args:
        runs: List of RunStatusReport instances.
        jobs: List of JobSpec instances across runs.
        search_text: Optional search substring matched against run ID and name.
        status_filter: Display status filter or ``ALL``.

    Returns:
        List of NiceGUI ``ui.tree`` root node dictionaries.
    """
    needle = search_text.strip().casefold()
    target_status = status_filter.strip().upper()
    jobs_by_run: dict[str, list[JobSpec]] = {}
    for job in jobs:
        jobs_by_run.setdefault(job.run_id, []).append(job)

    tree_nodes: list[dict[str, object]] = []
    for run in runs:
        run_status = resolve_run_display_status(run)
        if target_status not in ("", "ALL") and run_status != target_status:
            continue
        if needle and needle not in f"{run.run_id} {run.name or ''}".casefold():
            continue
        tree_nodes.append(
            build_single_run_tree_node(run, jobs_by_run.get(run.run_id, []))
        )
    return tree_nodes


def render_runs_section(
    pipeline: ExecutionPipeline,
    identity: Identity,
    runs: list[RunStatusReport],
    jobs: list[JobSpec],
    *,
    filter_state: dict[str, str] | None = None,
    expanded_nodes: set[str] | None = None,
    on_mutated: Callable[[], Awaitable[None]] | None = None,
    on_filter_run: Callable[[str], None] | None = None,
    drawer_host: Any = None,
) -> None:
    """Render expandable Runs & nested DAG tree view.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
        runs: List of RunStatusReport instances.
        jobs: List of JobSpec instances.
        filter_state: Optional mutable dict persisting search/status filter values.
        expanded_nodes: Optional mutable set persisting expanded tree node IDs.
        on_mutated: Optional async callback invoked after lifecycle mutations.
        on_filter_run: Optional callback to filter the jobs table to a run ID.
        drawer_host: Optional persistent NiceGUI container for slide-over drawers.
    """
    active_filters = (
        filter_state if filter_state is not None else {"search": "", "status": "ALL"}
    )
    ui.label("Runs & DAG Tree").classes("text-lg font-semibold mt-4")
    nodes = build_run_tree_nodes(
        runs,
        jobs,
        search_text=active_filters.get("search", ""),
        status_filter=active_filters.get("status", "ALL"),
    )
    if not nodes:
        ui.label("No matching runs.").classes("text-slate-300 text-sm")
        return

    runs_by_id = {r.run_id: r for r in runs}
    jobs_by_id = {j.id: j for j in jobs}

    async def _on_select_tree_node(ev: object) -> None:
        node_key = str(getattr(ev, "value", "") or "")
        if node_key.startswith("run:"):
            run_id = node_key.split(":", 1)[1]
            run_report = runs_by_id.get(run_id)
            if run_report is not None:
                await open_run_inspection_drawer(
                    pipeline,
                    identity,
                    run_report,
                    jobs,
                    on_mutated=on_mutated,
                    on_filter_run=on_filter_run,
                    drawer_host=drawer_host,
                )
        elif node_key.startswith("job:"):
            job_id = node_key.split(":", 1)[1]
            job = jobs_by_id.get(job_id)
            if job is not None:
                await open_job_inspection_drawer(
                    pipeline,
                    identity,
                    job,
                    run_report=runs_by_id.get(job.run_id),
                    all_jobs=jobs,
                    on_mutated=on_mutated,
                    on_filter_run=on_filter_run,
                    drawer_host=drawer_host,
                )

    def _on_expand_tree_nodes(ev: object) -> None:
        if expanded_nodes is None:
            return
        expanded_vals = getattr(ev, "value", None) or []
        expanded_nodes.clear()
        expanded_nodes.update(str(k) for k in expanded_vals)

    tree = ui.tree(
        nodes,
        label_key="label",
        node_key="id",
        on_select=_on_select_tree_node,
        on_expand=_on_expand_tree_nodes,
    ).classes("w-full border rounded p-2 mt-1")
    if expanded_nodes:
        tree.expand(list(expanded_nodes))
    tree.add_slot(
        "default-header",
        """
        <div class="row items-center q-gutter-sm">
            <q-badge
                :style="{ backgroundColor: props.node.badge_bg, color: '#ffffff', fontWeight: 700 }"
                class="px-2 py-0.5 text-xs rounded"
            >
                {{ props.node.status }}
            </q-badge>
            <span class="font-mono text-sm">{{ props.node.label }}</span>
        </div>
        """,
    )


__all__ = [
    "build_dag_job_subtree",
    "build_run_tree_nodes",
    "build_single_run_tree_node",
    "render_runs_section",
]
