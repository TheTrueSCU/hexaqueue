"""Unit tests for NiceGUI dashboard UI composition shell."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from hexastack_auth.domain.models import Identity
from nicegui import app as nicegui_app

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_dashboard.adapters import nicegui_ui
from hexaqueue_dashboard.adapters.auth import DashboardAuthManager
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

    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    ident = Identity(user_id="rjdw", roles=frozenset({"admin"}))

    await nicegui_ui._render_console_panel(pipeline, ident)

    for on_change_cb in captured_on_changes:
        on_change_cb(SimpleNamespace(value="r-test"))
    captured_buttons["Clear Filters"]()

    await captured_buttons["Refresh"]()
    await captured_timers[0]()
    assert len(js_calls) >= 2
    assert "changed: true" in js_calls[0]
    assert "changed: false" in js_calls[1]

    captured_buttons["Active Nodes & Topology"]()
    captured_buttons["Runs & DAG"]()
    captured_buttons["Jobs"]()

    captured_buttons["Sign Out"]()
    assert fake_storage.user.get("jwt") is None
