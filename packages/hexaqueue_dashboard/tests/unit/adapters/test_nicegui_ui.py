"""Unit tests for NiceGUI dashboard UI composition shell."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from hexastack_auth.domain.models import Identity
from nicegui import app as nicegui_app

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_dashboard.adapters import nicegui_ui
from hexaqueue_dashboard.adapters.auth import DashboardAuthManager
from hexaqueue_dashboard.adapters.ui import fairshare_view as fairshare_mod
from hexaqueue_dashboard.adapters.ui import history_view as history_mod
from hexaqueue_dashboard.adapters.ui import jobs_table as jobs_mod
from hexaqueue_dashboard.adapters.ui import nodes_view as nodes_mod
from hexaqueue_dashboard.adapters.ui import runs_tree as runs_mod
from hexaqueue_dashboard.adapters.ui import status as status_mod
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


def test_mount_dashboard_ui_registers_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify mount_dashboard_ui wires FastAPI app and static JS cleanly."""
    app = FastAPI()
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    manager = DashboardAuthManager(jwt_secret="test-secret-for-nicegui-mount-32bytes")

    called: dict[str, Any] = {}
    monkeypatch.setattr(
        nicegui_ui.ui,
        "run_with",
        lambda target_app, **kwargs: called.update(
            {"app": target_app, "kwargs": kwargs}
        ),
    )
    monkeypatch.setattr(nicegui_app, "add_static_file", lambda **_k: "/static/live.js")

    nicegui_ui.mount_dashboard_ui(app, pipeline, auth_manager=manager)
    assert called["app"] is app
    assert called["kwargs"]["language"] == "en-US"
    static_dir = nicegui_ui._resolve_static_dir()
    assert static_dir is not None and static_dir.is_dir()


@pytest.mark.asyncio
async def test_console_panel_refresh_and_filters(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: Any,
) -> None:
    """Verify _render_console_panel reactive refresh, filter sync, and logout."""
    fake_storage = SimpleNamespace(user={"jwt": "tok"})
    monkeypatch.setattr(nicegui_ui.nicegui_app, "storage", fake_storage)

    def _fake_refreshable(fn: Any) -> Any:
        fn.refresh = lambda: None
        return fn

    captured_buttons: dict[str, Any] = {}
    captured_timers: list[Any] = []
    captured_on_changes: list[Any] = []
    js_calls: list[str] = []

    def _fake_button(label: str = "", *_a: object, **kwargs: Any) -> fake_el:
        if "on_click" in kwargs:
            captured_buttons[label] = kwargs["on_click"]
        return fake_el()

    def _fake_input(*_a: object, **kwargs: Any) -> fake_el:
        if "on_change" in kwargs:
            captured_on_changes.append(kwargs["on_change"])
        return fake_el()

    fake_ui = SimpleNamespace(
        element=lambda *_a, **_k: fake_el(),
        card=lambda *_a, **_k: fake_el(),
        row=lambda *_a, **_k: fake_el(),
        column=lambda *_a, **_k: fake_el(),
        label=lambda *_a, **_k: fake_el(),
        input=_fake_input,
        select=_fake_input,
        table=lambda *_a, **_k: fake_el(),
        tree=lambda *_a, **_k: fake_el(),
        dialog=lambda *_a, **_k: fake_el(),
        button=_fake_button,
        notify=lambda *_a, **_k: None,
        navigate=SimpleNamespace(reload=lambda: None),
        header=lambda *_a, **_k: fake_el(),
        html=lambda *_a, **_k: fake_el(),
        add_body_html=lambda *_a, **_k: None,
        refreshable=_fake_refreshable,
        timer=lambda _i, cb: captured_timers.append(cb),
        run_javascript=lambda code, *_a, **_k: js_calls.append(str(code)),
    )
    monkeypatch.setattr(nicegui_ui, "ui", fake_ui)
    monkeypatch.setattr(status_mod, "ui", fake_ui)
    monkeypatch.setattr(runs_mod, "ui", fake_ui)
    monkeypatch.setattr(jobs_mod, "ui", fake_ui)
    monkeypatch.setattr(nodes_mod, "ui", fake_ui)
    monkeypatch.setattr(history_mod, "ui", fake_ui)
    monkeypatch.setattr(fairshare_mod, "ui", fake_ui)

    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    ident = Identity(user_id="rjdw", roles=frozenset({"admin", "user"}))

    await nicegui_ui._render_console_panel(pipeline, ident)

    for on_change_cb in captured_on_changes:
        res = on_change_cb(SimpleNamespace(value="user"))
        if inspect.isawaitable(res):
            awaited = await res
            assert awaited is None
        else:
            assert res is None
    captured_buttons["Clear Filters"]()

    js_calls.clear()
    await captured_buttons["Refresh"]()
    await captured_timers[0]()
    assert len(js_calls) >= 2
    assert "changed: true" in js_calls[0]
    assert "changed: false" in js_calls[1]

    captured_buttons["Active Nodes & Topology"]()
    captured_buttons["History Explorer"]()
    captured_buttons["Runs & DAG"]()
    captured_buttons["Jobs"]()

    captured_buttons["Sign Out"]()
    assert fake_storage.user.get("jwt") is None

    prev_fp = '{"kpi": {"node_count": 1}, "nodes": [["w-1", 10.0]], "jobs_runs": {"jobs": []}}'
    next_node_fp = '{"kpi": {"node_count": 1}, "nodes": [["w-1", 25.0]], "jobs_runs": {"jobs": []}}'
    any_j, kpi_j, body_j = nicegui_ui._selective_refresh_needed(
        "jobs", prev_fp, next_node_fp, force=False
    )
    assert any_j is True
    assert kpi_j is False
    assert body_j is False
    any_n, _kpi_n, body_n = nicegui_ui._selective_refresh_needed(
        "nodes", prev_fp, next_node_fp, force=False
    )
    assert any_n is True
    assert body_n is True
    _any_h, _kpi_h, body_h = nicegui_ui._selective_refresh_needed(
        "history", prev_fp, next_node_fp, force=False
    )
    assert body_h is False


def test_role_view_gating_and_fieldset_tab_groups(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: Any,
) -> None:
    """Verify Viewing-as role bounding and User/Admin `<fieldset>` tab groups."""
    from hexaqueue_core.domain.cqrs import ClusterStatsReport
    from hexaqueue_dashboard.adapters.ui.state import ConsoleUIState

    admin_ident = Identity(user_id="rjdw", roles=frozenset({"admin", "user"}))
    user_ident = Identity(user_id="bob", roles=frozenset({"user"}))

    assert nicegui_ui._resolve_is_admin_view(admin_ident, "admin") is True
    assert nicegui_ui._resolve_is_admin_view(admin_ident, "user") is False
    assert nicegui_ui._resolve_is_admin_view(user_ident, "admin") is False

    seen_buttons: list[str] = []
    seen_elements: list[str] = []
    fake_ui = SimpleNamespace(
        element=lambda tag, *_a, **_k: seen_elements.append(tag) or fake_el(),
        card=lambda *_a, **_k: fake_el(),
        row=lambda *_a, **_k: fake_el(),
        label=lambda *_a, **_k: fake_el(),
        button=lambda label="", *_a, **_k: seen_buttons.append(label) or fake_el(),
    )
    monkeypatch.setattr(nicegui_ui, "ui", fake_ui)

    stats = ClusterStatsReport(
        total_jobs=0,
        pending_jobs=0,
        running_jobs=0,
        completed_jobs=0,
        failed_jobs=0,
        active_workers=0,
    )
    snapshot = (stats, [], [], [], "{}")
    ui_state = ConsoleUIState()

    nicegui_ui._render_kpi_and_tabs(
        snapshot, ui_state, lambda *_a, **_k: None, is_admin_view=False
    )
    assert "Active Nodes & Topology" not in seen_buttons
    assert seen_elements.count("fieldset") == 1

    seen_buttons.clear()
    seen_elements.clear()
    nicegui_ui._render_kpi_and_tabs(
        snapshot, ui_state, lambda *_a, **_k: None, is_admin_view=True
    )
    assert "Active Nodes & Topology" in seen_buttons
    assert "Fair-Share & Quotas" in seen_buttons
    assert seen_elements.count("fieldset") == 2


def test_apply_body_refresh_updates_nodes_table_in_place() -> None:
    """Verify nodes tab heartbeats update table rows in place without full refresh."""
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from hexaqueue_core.domain.telemetry import NodeTelemetryPulse
    from hexaqueue_dashboard.adapters import nicegui_ui
    from hexaqueue_dashboard.adapters.ui.state import ConsoleUIState

    pulse = NodeTelemetryPulse(
        worker_id="node-local-01",
        cpu_utilization_pct=12.5,
        memory_used_mb=1024.0,
        memory_total_mb=4096.0,
        scratch_used_mb=100.0,
        scratch_total_mb=1000.0,
        load_average=(0.5, 0.4, 0.3),
        timestamp=datetime.now(UTC),
    )
    updated_calls = 0

    class FakeTable:
        def __init__(self) -> None:
            self.rows: list[dict[str, object]] = []

        def update(self) -> None:
            nonlocal updated_calls
            updated_calls += 1

    class FakeBody:
        def __init__(self) -> None:
            self.refreshed = 0

        def refresh(self) -> None:
            self.refreshed += 1

    table = FakeTable()
    body = FakeBody()
    ui_state = ConsoleUIState(tab="nodes")
    ui_state.node_table_ref["table"] = table
    ui_state.node_table_ref["workers"] = ("node-local-01",)

    next_data = (SimpleNamespace(), [pulse], [], [], "{}")
    nicegui_ui._apply_body_refresh(ui_state, next_data, body, force=False)
    assert updated_calls == 1
    assert body.refreshed == 0
    assert table.rows[0]["worker_id"] == "node-local-01"

    nicegui_ui._apply_body_refresh(ui_state, next_data, body, force=True)
    assert body.refreshed == 1

    # Different worker set falls back to full refresh
    ui_state.node_table_ref["workers"] = ("node-other",)
    nicegui_ui._apply_body_refresh(ui_state, next_data, body, force=False)
    assert body.refreshed == 2
