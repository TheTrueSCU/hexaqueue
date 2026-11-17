"""Component-scoped UI state dataclasses for the Hexaqueue Operator Console.

Notes/Architectural Intent:
    Segregates console UI state by component (`FilterUIState`,
    `JobsTableUIState`, `RunsTreeUIState`, `DrawerUIState`) and bundles them
    into `ConsoleUIState` so each view receives only the minimal state it
    owns across `@ui.refreshable` updates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActiveDrawerState:
    """Tracks an open inspection slide-over for live in-place SSE updates.

    Notes/Architectural Intent:
        Holds the open `ui.dialog()` and inner `ui.card()` references so
        background SSE refreshes can update job/run status, timelines, and
        logs in place without closing or flickering the dialog.
    """

    kind: str
    target_id: str
    card: Any
    dialog: Any


@dataclass
class FilterUIState:
    """Shared search/status filter state and widget references."""

    search: str = ""
    status: str = "ALL"
    controls: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, str]:
        """Return ``{"search": ..., "status": ...}`` mapping for filter helpers."""
        return {"search": self.search, "status": self.status}


@dataclass
class JobsTableUIState:
    """Sort, pagination, and windowed history limit state for the Jobs table."""

    pagination: dict[str, Any] = field(
        default_factory=lambda: {
            "rowsPerPage": 15,
            "sortBy": "updated_at",
            "descending": True,
            "page": 1,
        }
    )
    history_limit: int = 50


@dataclass
class RunsTreeUIState:
    """Expanded node and windowed history limit state for the Runs & DAG tree."""

    expanded_nodes: set[str] = field(default_factory=set)
    history_limit: int = 50


@dataclass
class HistoryUIState:
    """Search, scope, date-bound, and pagination state for the History Explorer tab."""

    kind: str = "jobs"
    search: str = ""
    status: str = "ALL"
    date_from: str = ""
    date_to: str = ""
    page: int = 1
    page_size: int = 25


@dataclass
class DrawerUIState:
    """Persistent drawer host and currently open slide-over handle."""

    host: Any = None
    active: ActiveDrawerState | None = None


@dataclass
class ConsoleUIState:
    """Top-level wrapper container bundling all component UI state objects.

    Notes/Architectural Intent:
        Allows `_render_console_panel` to hold one cohesive state container
        while passing only the minimal component state (`filters`, `jobs_table`,
        `runs_tree`, `drawer`) to each child view.
    """

    tab: str = "jobs"
    active_role: str = "user"
    filters: FilterUIState = field(default_factory=FilterUIState)
    jobs_table: JobsTableUIState = field(default_factory=JobsTableUIState)
    runs_tree: RunsTreeUIState = field(default_factory=RunsTreeUIState)
    history: HistoryUIState = field(default_factory=HistoryUIState)
    drawer: DrawerUIState = field(default_factory=DrawerUIState)
    node_metrics_history: dict[str, list[dict[str, float | str]]] = field(
        default_factory=dict
    )
    node_table_ref: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ActiveDrawerState",
    "ConsoleUIState",
    "DrawerUIState",
    "FilterUIState",
    "HistoryUIState",
    "JobsTableUIState",
    "RunsTreeUIState",
]
