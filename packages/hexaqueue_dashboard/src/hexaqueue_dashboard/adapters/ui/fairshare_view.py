"""Fair-Share hierarchy and elastic OCI worker pool quota view.

Notes/Architectural Intent:
    Queries `GetFairShareTreeQuery` through `ExecutionPipeline` and pairs it
    with elastic OCI worker pool capacity telemetry (`hq-worker-pool-a1`)
    using WCAG 2.1 AA high-contrast cards, tables, and `ui.tree`.
"""

from __future__ import annotations

import os

from hexastack_auth.domain.models import Identity
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_ui.adapters.nicegui import dispatch_query
from nicegui import ui

from hexaqueue_core.domain.cqrs import ClusterStatsReport, GetFairShareTreeQuery
from hexaqueue_core.domain.explainability import (
    FairShareNodeReport,
    FairShareTreeReport,
)
from hexaqueue_dashboard.adapters.ui.nodes_view import _is_baseline_worker
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse

FAIRSHARE_COLUMNS: list[dict[str, object]] = [
    {"name": "id", "label": "Account / User", "field": "id", "align": "left"},
    {"name": "parent_id", "label": "Parent", "field": "parent_id", "align": "left"},
    {"name": "shares", "label": "Shares", "field": "shares", "align": "right"},
    {
        "name": "target_share",
        "label": "Target %",
        "field": "target_share",
        "align": "right",
    },
    {
        "name": "decayed_usage",
        "label": "Decayed Usage",
        "field": "decayed_usage",
        "align": "right",
    },
    {
        "name": "fairshare_factor",
        "label": "Fair-Share F",
        "field": "fairshare_factor",
        "align": "right",
    },
]


def _flatten_fairshare_rows(node: FairShareNodeReport) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {
            "id": node.id,
            "parent_id": node.parent_id or "—",
            "shares": f"{node.shares:.1f}",
            "target_share": f"{node.target_share * 100:.1f}%",
            "decayed_usage": f"{node.decayed_usage:.2f}",
            "fairshare_factor": f"{node.fairshare_factor:.3f}",
        }
    ]
    for child in node.children:
        rows.extend(_flatten_fairshare_rows(child))
    return rows


def build_fairshare_tree_nodes(
    node: FairShareNodeReport,
) -> list[dict[str, object]]:
    """Convert FairShareNodeReport hierarchy into NiceGUI `ui.tree` nodes.

    Args:
        node: Root FairShareNodeReport node.

    Returns:
        Single-element list containing the hierarchical tree node dict.
    """
    return [
        {
            "id": f"fs:{node.id}",
            "label": (
                f"{node.id} — shares={node.shares:.1f}, "
                f"target={node.target_share * 100:.1f}%, "
                f"F={node.fairshare_factor:.3f}"
            ),
            "children": [
                build_fairshare_tree_nodes(child)[0] for child in node.children
            ],
        }
    ]


async def render_fairshare_section(
    pipeline: ExecutionPipeline,
    identity: Identity,
    nodes: list[NodeTelemetryPulse],
    stats: ClusterStatsReport,
) -> None:
    """Render Fair-Share hierarchy and elastic OCI worker pool quota panel.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
        nodes: Active worker NodeTelemetryPulse records.
        stats: Aggregate ClusterStatsReport metrics.
    """
    ui.label("Fair-Share & OCI Pool Quotas").classes("text-lg font-semibold mt-4")

    baseline_nodes = [n for n in nodes if _is_baseline_worker(n.worker_id)]
    pool_nodes = [n for n in nodes if not _is_baseline_worker(n.worker_id)]
    pool_name = (
        os.environ.get("HEXAQUEUE_OCI_POOL_NAME", "").strip() or "hq-worker-pool-a1"
    )
    pool_status = (
        "Active"
        if pool_nodes
        else ("Provisioning" if stats.pending_jobs > 0 else "Idle (Scaled Down)")
    )
    baseline_status = "Active" if baseline_nodes else "Offline"
    with ui.row().classes("w-full gap-4 mt-2"):
        with ui.card().classes("p-4"):
            ui.label(f"Pool: {pool_name}").classes("font-semibold")
            ui.label(
                f"Status: {pool_status} | Pool Workers: {len(pool_nodes)}"
            ).classes("text-xs font-mono text-slate-300 mt-1")
        with ui.card().classes("p-4"):
            ui.label("Baseline Capacity").classes("font-semibold")
            ui.label(
                f"Status: {baseline_status} | Baseline Workers: {len(baseline_nodes)}"
            ).classes("text-xs font-mono text-slate-300 mt-1")
        with ui.card().classes("p-4"):
            ui.label("Queue Demand").classes("font-semibold")
            ui.label(
                f"Running: {stats.running_jobs} | Pending: {stats.pending_jobs}"
            ).classes("text-xs font-mono text-slate-300 mt-1")

    is_admin = "admin" in identity.roles
    report: FairShareTreeReport | None = None
    error_msg: str | None = None
    try:
        report = await dispatch_query(
            pipeline,
            GetFairShareTreeQuery(requesting_user=identity.user_id, is_admin=is_admin),
        )
    except Exception as exc:
        error_msg = str(exc)

    if report is None:
        ui.label(f"Fair-share tree unavailable: {error_msg or 'no data'}").classes(
            "text-sm text-slate-300 mt-3"
        )
        return

    ui.label(
        f"Half-Life: {report.half_life_seconds:.0f}s | "
        f"Total Decayed Usage: {report.total_decayed_usage:.2f}"
    ).classes("text-xs font-mono text-slate-300 mt-3")

    tree_nodes = build_fairshare_tree_nodes(report.root)
    ui.tree(tree_nodes, label_key="label", node_key="id").classes(
        "w-full border rounded p-2 mt-2"
    )
    rows = _flatten_fairshare_rows(report.root)
    ui.table(columns=FAIRSHARE_COLUMNS, rows=rows, row_key="id").classes("w-full mt-3")


__all__ = [
    "build_fairshare_tree_nodes",
    "FAIRSHARE_COLUMNS",
    "render_fairshare_section",
]
