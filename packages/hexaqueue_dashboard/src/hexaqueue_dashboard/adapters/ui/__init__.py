"""Modular NiceGUI view components for the Hexaqueue Operator Console.

Notes/Architectural Intent:
    Decomposes dashboard UI concerns (status badges, login, jobs table, runs DAG
    tree, inspection drawer) into focused, independently testable view modules.
"""

from hexaqueue_dashboard.adapters.ui.inspection_drawer import (
    dispatch_lifecycle_action,
    open_cancel_run_dialog,
    open_job_inspection_drawer,
    open_run_inspection_drawer,
    render_drawer_dag_links,
    render_drawer_explain_and_logs,
    render_drawer_state_timeline,
)
from hexaqueue_dashboard.adapters.ui.jobs_table import (
    build_job_rows,
    compute_filtered_kpi_counts,
    filter_jobs,
    render_jobs_section,
)
from hexaqueue_dashboard.adapters.ui.login import (
    render_login_panel,
    resolve_session_identity,
)
from hexaqueue_dashboard.adapters.ui.nodes_view import (
    build_node_rows,
    generate_cluster_topology_svg,
    render_nodes_section,
)
from hexaqueue_dashboard.adapters.ui.runs_tree import (
    build_dag_job_subtree,
    build_run_tree_nodes,
    build_single_run_tree_node,
    render_runs_section,
)
from hexaqueue_dashboard.adapters.ui.status import (
    STATUS_BADGE_COLORS,
    TERMINAL_DISPLAY_STATES,
    render_live_status_widget,
    resolve_job_display_status,
    resolve_run_display_status,
)

__all__ = [
    "build_dag_job_subtree",
    "build_job_rows",
    "build_node_rows",
    "build_run_tree_nodes",
    "build_single_run_tree_node",
    "compute_filtered_kpi_counts",
    "dispatch_lifecycle_action",
    "filter_jobs",
    "generate_cluster_topology_svg",
    "open_cancel_run_dialog",
    "open_job_inspection_drawer",
    "open_run_inspection_drawer",
    "render_drawer_dag_links",
    "render_drawer_explain_and_logs",
    "render_drawer_state_timeline",
    "render_jobs_section",
    "render_live_status_widget",
    "render_login_panel",
    "render_nodes_section",
    "render_runs_section",
    "resolve_job_display_status",
    "resolve_run_display_status",
    "resolve_session_identity",
    "STATUS_BADGE_COLORS",
    "TERMINAL_DISPLAY_STATES",
]
