"""Unit tests for login panel and session identity resolution."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from hexastack_auth.domain.models import Identity

from hexaqueue_dashboard.adapters.auth import DashboardAuthManager
from hexaqueue_dashboard.adapters.ui import login as login_mod
from hexaqueue_dashboard.adapters.ui import status as status_mod
from hexaqueue_dashboard.domain.rbac import RbacPrincipal


def test_login_session_resolution_and_panel(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: Any,
) -> None:
    """Verify JWT resolution and login card rendering."""
    fake_storage = SimpleNamespace(user={})
    monkeypatch.setattr(login_mod.nicegui_app, "storage", fake_storage)

    fake_ui = SimpleNamespace(
        card=lambda *_a, **_k: fake_el(),
        row=lambda *_a, **_k: fake_el(),
        label=lambda *_a, **_k: fake_el(),
        input=lambda *_a, **_k: fake_el(),
        button=lambda *_a, **_k: fake_el(),
        html=lambda *_a, **_k: fake_el(),
        add_body_html=lambda *_a, **_k: None,
        navigate=SimpleNamespace(reload=lambda: None),
    )
    monkeypatch.setattr(login_mod, "ui", fake_ui)
    monkeypatch.setattr(status_mod, "ui", fake_ui)

    manager = DashboardAuthManager(jwt_secret="test-secret-for-login-panel-32bytes")
    empty_res = login_mod.resolve_session_identity(manager)
    assert empty_res is None

    fake_storage.user["jwt"] = "invalid-token"
    bad_res = login_mod.resolve_session_identity(manager)
    assert bad_res is None

    ident = Identity(user_id="rjdw", roles=frozenset({"admin"}))
    fake_storage.user["jwt"] = manager.issue_token(ident)
    good_res = login_mod.resolve_session_identity(manager)
    assert good_res is not None
    assert good_res.user_id == "rjdw"

    captured: dict[str, Any] = {}

    def _cap_btn(label: str = "", *_a: object, **kwargs: Any) -> Any:
        if "on_click" in kwargs:
            captured[label] = kwargs["on_click"]
        return fake_el()

    fake_ui.button = _cap_btn
    login_mod.render_login_panel(manager, live_status_js_url="/static/live.js")
    assert "Sign In" in captured

    # Verify Change Password modal validation & rotation
    inputs: list[Any] = []
    notifications: list[str] = []
    fake_ui.dialog = lambda *_a, **_k: fake_el()
    fake_ui.notify = lambda msg, **_k: notifications.append(str(msg))
    fake_ui.input = lambda *_a, **_k: inputs.append(el := fake_el()) or el
    manager.rbac_store.upsert_principal(
        RbacPrincipal(
            principal_id="rjdw",
            hashed_secret=manager.hash_secret("old-secret-pw"),
            roles=frozenset({"admin"}),
        )
    )
    login_mod.open_change_password_dialog(manager, ident)
    assert "Update Password" in captured
    inputs[0].value = "old-secret-pw"
    inputs[1].value = "new-secret-pw-123"
    inputs[2].value = "mismatch"
    captured["Update Password"]()
    assert notifications == []

    inputs[2].value = "new-secret-pw-123"
    captured["Update Password"]()
    assert notifications == ["Password updated."]
