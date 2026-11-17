"""Unit tests for component-scoped UI state dataclasses."""

from __future__ import annotations

from hexaqueue_dashboard.adapters.ui.state import (
    ActiveDrawerState,
    ConsoleUIState,
    DrawerUIState,
    FilterUIState,
    JobsTableUIState,
    RunsTreeUIState,
)


def test_console_ui_state_defaults_and_component_isolation() -> None:
    """Verify component-scoped UI state defaults and ActiveDrawerState tracking."""
    state_a = ConsoleUIState()
    state_b = ConsoleUIState()

    assert state_a.tab == "jobs"
    assert isinstance(state_a.filters, FilterUIState)
    assert isinstance(state_a.jobs_table, JobsTableUIState)
    assert isinstance(state_a.runs_tree, RunsTreeUIState)
    assert isinstance(state_a.drawer, DrawerUIState)
    assert state_a.filters.as_dict() == {"search": "", "status": "ALL"}
    assert state_a.jobs_table.pagination["sortBy"] == "updated_at"
    assert state_a.jobs_table.pagination["descending"] is True
    assert state_a.drawer.active is None

    state_a.runs_tree.expanded_nodes.add("run:r-1")
    assert "run:r-1" not in state_b.runs_tree.expanded_nodes

    drawer = ActiveDrawerState(kind="job", target_id="j-1", card="c", dialog="d")
    state_a.drawer.active = drawer
    assert state_a.drawer.active.kind == "job"
    assert state_a.drawer.active.target_id == "j-1"
