"""Modular NiceGUI view components for the Hexaqueue Operator Console.

Notes/Architectural Intent:
    Decomposes dashboard UI concerns (status badges, login, jobs table, runs DAG
    tree, inspection drawer) into focused, independently testable view modules.
"""

from hexaqueue_dashboard.adapters.ui.fairshare_view import (
    build_fairshare_tree_nodes,
    render_fairshare_section,
)
from hexaqueue_dashboard.adapters.ui.history_view import (
    build_history_run_rows,
    filter_history_runs,
    paginate_history_items,
    render_history_section,
)
from hexaqueue_dashboard.adapters.ui.inspection_drawer import (
    dispatch_lifecycle_action,
    open_cancel_run_dialog,
    open_job_inspection_drawer,
    open_run_inspection_drawer,
    refresh_active_drawer,
    render_drawer_dag_links,
    render_drawer_explain_and_logs,
    render_drawer_run_timeline,
    render_drawer_state_timeline,
)
from hexaqueue_dashboard.adapters.ui.jobs_table import (
    build_job_rows,
    compute_filtered_kpi_counts,
    filter_jobs,
    render_jobs_section,
    sort_job_rows,
)
from hexaqueue_dashboard.adapters.ui.login import (
    open_change_password_dialog,
    render_login_panel,
    resolve_session_identity,
)
from hexaqueue_dashboard.adapters.ui.logs_view import (
    build_log_pre_html,
    fetch_job_logs,
    format_log_lines,
    render_live_log_viewer,
    render_live_logs_page,
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
from hexaqueue_dashboard.adapters.ui.state import (
    ActiveDrawerState,
    ConsoleUIState,
    DrawerUIState,
    FilterUIState,
    HistoryUIState,
    JobsTableUIState,
    RunsTreeUIState,
)
from hexaqueue_dashboard.adapters.ui.status import (
    STATUS_BADGE_COLORS,
    STATUS_SORT_RANK,
    TERMINAL_DISPLAY_STATES,
    matches_status_filter,
    render_live_status_widget,
    resolve_job_display_status,
    resolve_run_display_status,
    status_sort_rank,
)

__all__ = [
    "ActiveDrawerState",
    "build_dag_job_subtree",
    "build_fairshare_tree_nodes",
    "build_history_run_rows",
    "build_job_rows",
    "build_log_pre_html",
    "build_node_rows",
    "build_run_tree_nodes",
    "build_single_run_tree_node",
    "compute_filtered_kpi_counts",
    "ConsoleUIState",
    "dispatch_lifecycle_action",
    "DrawerUIState",
    "fetch_job_logs",
    "filter_history_runs",
    "filter_jobs",
    "FilterUIState",
    "format_log_lines",
    "generate_cluster_topology_svg",
    "HistoryUIState",
    "JobsTableUIState",
    "matches_status_filter",
    "open_cancel_run_dialog",
    "open_change_password_dialog",
    "open_job_inspection_drawer",
    "open_run_inspection_drawer",
    "paginate_history_items",
    "refresh_active_drawer",
    "render_drawer_dag_links",
    "render_drawer_explain_and_logs",
    "render_drawer_run_timeline",
    "render_drawer_state_timeline",
    "render_fairshare_section",
    "render_history_section",
    "render_jobs_section",
    "render_live_log_viewer",
    "render_live_logs_page",
    "render_live_status_widget",
    "render_login_panel",
    "render_nodes_section",
    "render_runs_section",
    "resolve_job_display_status",
    "resolve_run_display_status",
    "resolve_session_identity",
    "RunsTreeUIState",
    "sort_job_rows",
    "STATUS_BADGE_COLORS",
    "status_sort_rank",
    "STATUS_SORT_RANK",
    "TERMINAL_DISPLAY_STATES",
]
