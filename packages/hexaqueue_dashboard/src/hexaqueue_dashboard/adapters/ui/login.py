"""NiceGUI authentication, session resolution, and login card view.

Notes/Architectural Intent:
    Handles JWT verification from NiceGUI per-user storage and renders the
    WCAG 2.1 AA sign-in card with Enter-key submission and tunnel liveness badge.
"""

from __future__ import annotations

from hexastack_auth.domain.models import Identity
from nicegui import app as nicegui_app
from nicegui import ui

from hexaqueue_dashboard.adapters.auth import DashboardAuthManager
from hexaqueue_dashboard.adapters.ui.status import render_live_status_widget


def resolve_session_identity(auth_manager: DashboardAuthManager) -> Identity | None:
    """Resolve authenticated Identity from NiceGUI per-user session storage.

    Args:
        auth_manager: DashboardAuthManager used to verify stored JWT.

    Returns:
        Verified Identity if present and valid, otherwise None.
    """
    token = nicegui_app.storage.user.get("jwt")
    if not token:
        return None
    try:
        return auth_manager.verify_token(str(token))
    except Exception:
        nicegui_app.storage.user.pop("jwt", None)
        return None


def render_login_panel(
    auth_manager: DashboardAuthManager,
    *,
    live_status_js_url: str | None = None,
) -> None:
    """Render the NiceGUI login card for `rjdw` / `hexaqueue-ci` web credentials.

    Args:
        auth_manager: DashboardAuthManager validating credentials.
        live_status_js_url: Optional URL for the static `live_status.js` script.
    """
    with ui.card().classes("w-full max-w-md mx-auto mt-12 p-6"):
        with ui.row().classes("w-full items-center justify-between mb-2"):
            ui.label("Hexaqueue Operator Sign In").classes("text-xl font-bold")
            render_live_status_widget(live_status_js_url, mode="tunnel")
        username = ui.input("Username", placeholder="rjdw").classes("w-full")
        password = ui.input(
            "Web Password / CI Token", password=True, password_toggle_button=True
        ).classes("w-full")
        error_label = ui.label("").classes("text-red-500 text-sm")

        def _handle_login() -> None:
            try:
                identity = auth_manager.authenticate_user(
                    username.value or "", password.value or ""
                )
                nicegui_app.storage.user["jwt"] = auth_manager.issue_token(identity)
                ui.navigate.reload()
            except Exception:
                error_label.text = "Invalid username or credential."

        ui.button("Sign In", on_click=_handle_login, icon="login").props(
            'aria-label="Sign in to Hexaqueue Dashboard"'
        ).tooltip("Authenticate with Hexaqueue web credentials")
        username.on("keydown.enter", _handle_login)
        password.on("keydown.enter", _handle_login)


__all__ = [
    "render_login_panel",
    "resolve_session_identity",
]
