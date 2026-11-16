"""Unit tests for NiceGUI dashboard UI mounting."""

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
from hexaqueue_dashboard.adapters.nicegui_ui import (
    _render_console_panel,
    _render_jobs_section,
    _render_login_panel,
    _resolve_session_identity,
    mount_dashboard_ui,
)
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


def test_mount_dashboard_ui_registers_nicegui_and_auth_manager() -> None:
    """Verify mount_dashboard_ui attaches auth_manager and NiceGUI routes."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    app = FastAPI()
    manager = DashboardAuthManager(jwt_secret="test-secret-for-nicegui-mount-32bytes")

    mount_dashboard_ui(app, pipeline, auth_manager=manager, mount_path="/dashboard/ui")

    bound_manager = getattr(app.state, "auth_manager", None)
    assert bound_manager is manager
    route_paths = {getattr(r, "path", "") for r in nicegui_app.routes}
    has_ui_route = "/dashboard/ui" in route_paths
    assert has_ui_route is True


class _FakeElement:
    def __init__(self, value: str = "") -> None:
        self.value = value
        self.text = ""

    def __enter__(self) -> _FakeElement:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def classes(self, *_args: object, **_kwargs: object) -> _FakeElement:
        return self

    def props(self, *_args: object, **_kwargs: object) -> _FakeElement:
        return self

    def tooltip(self, *_args: object, **_kwargs: object) -> _FakeElement:
        return self


@pytest.mark.asyncio
async def test_nicegui_ui_identity_and_panels(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify NiceGUI identity resolution, login panel, and console rendering."""
    fake_storage = SimpleNamespace(user={})
    monkeypatch.setattr(nicegui_ui.nicegui_app, "storage", fake_storage)

    def _fake_refreshable(fn):  # type: ignore[no-untyped-def]
        fn.refresh = lambda: None
        return fn

    captured_buttons: dict[str, Any] = {}
    captured_timers: list[Any] = []
    js_calls: list[str] = []

    def _fake_button(label: str = "", *args: object, **kwargs: Any) -> _FakeElement:
        if "on_click" in kwargs:
            captured_buttons[label] = kwargs["on_click"]
        return _FakeElement()

    def _fake_timer(_interval: float, callback: Any) -> None:
        captured_timers.append(callback)

    fake_ui = SimpleNamespace(
        card=lambda *_a, **_k: _FakeElement(),
        row=lambda *_a, **_k: _FakeElement(),
        column=lambda *_a, **_k: _FakeElement(),
        label=lambda *_a, **_k: _FakeElement(),
        input=lambda *_a, **_k: _FakeElement(),
        button=_fake_button,
        separator=lambda *_a, **_k: _FakeElement(),
        notify=lambda *_a, **_k: None,
        navigate=SimpleNamespace(reload=lambda: None),
        header=lambda *_a, **_k: _FakeElement(),
        html=lambda *_a, **_k: _FakeElement(),
        add_body_html=lambda *_a, **_k: None,
        refreshable=_fake_refreshable,
        timer=_fake_timer,
        run_javascript=lambda code, *_a, **_k: js_calls.append(str(code)),
    )
    monkeypatch.setattr(nicegui_ui, "ui", fake_ui)

    manager = DashboardAuthManager(jwt_secret="test-secret-for-nicegui-mount-32bytes")
    assert _resolve_session_identity(manager) is None

    fake_storage.user["jwt"] = "not-a-valid-jwt"
    assert _resolve_session_identity(manager) is None

    ident = Identity(user_id="rjdw", roles=frozenset({"admin"}))
    fake_storage.user["jwt"] = manager.issue_token(ident)
    resolved = _resolve_session_identity(manager)
    assert resolved is not None
    assert resolved.user_id == "rjdw"

    _render_login_panel(manager)

    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    await _render_jobs_section(pipeline, ident)
    await _render_console_panel(pipeline, ident)

    # Exercise reactive refresh, timer tick, and sign-out callbacks
    refresh_cb = captured_buttons["Refresh"]
    await refresh_cb()
    timer_cb = captured_timers[0]
    await timer_cb()
    js_count = len(js_calls)
    assert js_count >= 2
    assert "changed: true" in js_calls[0]
    assert "changed: false" in js_calls[1]

    logout_cb = captured_buttons["Sign Out"]
    logout_cb()
    jwt_after_logout = fake_storage.user.get("jwt")
    assert jwt_after_logout is None
