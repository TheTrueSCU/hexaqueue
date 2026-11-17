"""Active compute nodes table and diagrams-generated cluster topology SVG view.

Notes/Architectural Intent:
    Renders live worker node telemetry (`NodeTelemetryPulse`) as an interactive
    table alongside an up-to-date `diagrams`-generated cluster topology SVG
    showing the controller, Oracle ADB, Object Storage CAS, and active workers.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from diagrams import Cluster, Diagram
from diagrams.oci.compute import VM
from diagrams.oci.database import Autonomous
from diagrams.oci.storage import ObjectStorage
from nicegui import ui

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse

_logger = logging.getLogger(__name__)

NODE_TABLE_COLUMNS: list[dict[str, object]] = [
    {
        "name": "worker_id",
        "label": "Node / Worker ID",
        "field": "worker_id",
        "sortable": True,
        "align": "left",
    },
    {
        "name": "active_jobs",
        "label": "Active Jobs",
        "field": "active_jobs",
        "sortable": True,
        "align": "center",
    },
    {
        "name": "cpu_pct",
        "label": "CPU %",
        "field": "cpu_pct",
        "sortable": True,
        "align": "right",
    },
    {
        "name": "ram_usage",
        "label": "RAM (Used / Total)",
        "field": "ram_usage",
        "sortable": True,
        "align": "right",
    },
    {
        "name": "load_1m",
        "label": "Load (1m)",
        "field": "load_1m",
        "sortable": True,
        "align": "right",
    },
    {
        "name": "last_seen",
        "label": "Last Heartbeat",
        "field": "last_seen",
        "sortable": True,
        "align": "left",
    },
]


def build_node_rows(
    nodes: list[NodeTelemetryPulse],
    jobs: list[JobSpec] | None = None,
) -> list[dict[str, object]]:
    """Transform NodeTelemetryPulse records into sortable ui.table rows.

    Args:
        nodes: List of worker NodeTelemetryPulse snapshots.
        jobs: Optional list of JobSpec instances to resolve active job IDs per worker.

    Returns:
        List of row dictionaries for NiceGUI ``ui.table``.
    """
    leased_by_worker: dict[str, list[str]] = {}
    for job in jobs or []:
        if job.assigned_worker_id and str(job.state) in (
            "RUNNING",
            "PROVISIONING",
            "CLEANUP",
        ):
            leased_by_worker.setdefault(job.assigned_worker_id, []).append(job.id)

    rows: list[dict[str, object]] = []
    for pulse in nodes:
        leased = leased_by_worker.get(pulse.worker_id, [])
        active_label = (
            f"{pulse.active_jobs} ({', '.join(leased)})"
            if leased
            else str(pulse.active_jobs)
        )
        rows.append(
            {
                "worker_id": pulse.worker_id,
                "active_jobs": active_label,
                "cpu_pct": f"{pulse.cpu_utilization_pct:.1f}%",
                "ram_usage": f"{pulse.memory_used_mb} / {pulse.memory_total_mb} MB",
                "load_1m": f"{pulse.load_average[0]:.2f}",
                "last_seen": pulse.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"),
            }
        )
    return rows


def _fallback_topology_svg(nodes: list[NodeTelemetryPulse]) -> str:
    """Return an accessible fallback SVG when Graphviz `dot` is unavailable."""
    worker_count = len(nodes)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 160" '
        'role="img" aria-label="Hexaqueue cluster topology diagram" '
        'style="width:100%;max-width:640px;height:auto;">'
        '<rect width="640" height="160" fill="#ffffff" rx="8"/>'
        '<rect x="20" y="50" width="160" height="60" rx="6" fill="#1d4ed8"/>'
        '<text x="100" y="85" text-anchor="middle" fill="#ffffff" font-size="13">'
        "Controller</text>"
        '<rect x="240" y="20" width="160" height="50" rx="6" fill="#0f766e"/>'
        '<text x="320" y="50" text-anchor="middle" fill="#ffffff" font-size="13">'
        "Oracle ADB</text>"
        '<rect x="240" y="90" width="160" height="50" rx="6" fill="#374151"/>'
        '<text x="320" y="120" text-anchor="middle" fill="#ffffff" font-size="13">'
        "Object Storage</text>"
        '<rect x="450" y="50" width="170" height="60" rx="6" fill="#15803d"/>'
        '<text x="535" y="85" text-anchor="middle" fill="#ffffff" font-size="13">'
        f"Workers ({worker_count})</text>"
        "</svg>"
    )


def generate_cluster_topology_svg(
    nodes: list[NodeTelemetryPulse],
    jobs: list[JobSpec] | None = None,
) -> str:
    """Generate an up-to-date cluster topology SVG using `diagrams`.

    Args:
        nodes: Active worker NodeTelemetryPulse records.
        jobs: Optional JobSpec list to annotate running jobs per worker.

    Returns:
        Inline SVG markup string representing controller, ADB, CAS, and workers.
    """
    running_by_worker: dict[str, int] = {}
    for job in jobs or []:
        if job.assigned_worker_id and str(job.state) in (
            "RUNNING",
            "PROVISIONING",
            "CLEANUP",
        ):
            running_by_worker[job.assigned_worker_id] = (
                running_by_worker.get(job.assigned_worker_id, 0) + 1
            )

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_base = str(Path(tmpdir) / "hexaqueue_topology")
            with Diagram(
                "Hexaqueue Cluster Topology",
                filename=out_base,
                outformat="svg",
                show=False,
                direction="LR",
            ):
                controller = VM("Controller\n(hexaqueue-server)")
                adb = Autonomous("Oracle ADB\n(hexaqueue_tp)")
                cas = ObjectStorage("Collateral CAS\n(OCI Bucket)")
                controller >> adb
                controller >> cas

                with Cluster(f"Active Worker Pool ({len(nodes)})"):
                    if nodes:
                        for pulse in nodes:
                            running_cnt = running_by_worker.get(
                                pulse.worker_id, pulse.active_jobs
                            )
                            worker_node = VM(
                                f"{pulse.worker_id}\n"
                                f"CPU {pulse.cpu_utilization_pct:.0f}% | "
                                f"Jobs {running_cnt}"
                            )
                            controller >> worker_node
                    else:
                        idle = VM("No active workers")
                        controller >> idle

            svg_path = Path(f"{out_base}.svg")
            if svg_path.is_file():
                svg_text = svg_path.read_text(encoding="utf-8")
                svg_start = svg_text.find("<svg")
                return svg_text[svg_start:] if svg_start != -1 else svg_text
    except Exception as exc:
        _logger.debug("Falling back to static topology SVG: %s", exc)
    return _fallback_topology_svg(nodes)


def render_nodes_section(
    nodes: list[NodeTelemetryPulse],
    jobs: list[JobSpec] | None = None,
) -> None:
    """Render Active Nodes telemetry table and diagrams-generated topology SVG.

    Args:
        nodes: Active worker NodeTelemetryPulse list.
        jobs: Optional JobSpec list for worker job annotations.
    """
    ui.label("Active Nodes & Cluster Topology").classes("text-lg font-semibold mt-4")
    if not nodes:
        ui.label("No active worker nodes reporting telemetry.").classes(
            "text-slate-300 text-sm"
        )
    else:
        rows = build_node_rows(nodes, jobs)
        ui.table(
            columns=NODE_TABLE_COLUMNS,
            rows=rows,
            row_key="worker_id",
            pagination={"rowsPerPage": 10, "sortBy": "worker_id", "descending": False},
        ).classes("w-full mt-2")

    ui.label("Cluster Topology").classes("text-md font-semibold mt-4")
    svg_markup = generate_cluster_topology_svg(nodes, jobs)
    ui.html(
        '<div role="img" aria-label="Hexaqueue cluster topology diagram" '
        'class="w-full overflow-x-auto bg-white rounded p-3 mt-1">'
        f"{svg_markup}"
        "</div>",
        sanitize=False,
    )


__all__ = [
    "build_node_rows",
    "generate_cluster_topology_svg",
    "NODE_TABLE_COLUMNS",
    "render_nodes_section",
]
