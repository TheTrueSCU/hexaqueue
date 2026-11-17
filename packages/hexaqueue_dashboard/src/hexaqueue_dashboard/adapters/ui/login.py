"""NiceGUI authentication, session resolution, and login card view.

Notes/Architectural Intent:
    Handles JWT verification from NiceGUI per-user storage and renders the
    WCAG 2.1 AA sign-in card with Enter-key submission and tunnel liveness badge.
"""

from __future__ import annotations

from fastapi import HTTPException
from hexastack_auth.domain.models import Identity
from nicegui import app as nicegui_app
from nicegui import ui
from pydantic import SecretStr

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


def open_change_password_dialog(
    auth_manager: DashboardAuthManager,
    identity: Identity,
) -> None:
    """Open an accessible Change Password modal backed by `rotate_password()`.

    Args:
        auth_manager: DashboardAuthManager handling credential verification & hashing.
        identity: Verified caller Identity whose credential is being rotated.

    Notes/Architectural Intent:
        Mirrors `hq auth rotate-password` in the web console without coupling
        to `hexaqueue_cli`, enforcing password confirmation and current
        credential verification.
    """
    with ui.dialog() as dialog, ui.card().classes("w-96 max-w-full p-6 gap-3"):
        ui.label("Change Password").classes("text-lg font-bold")
        current_input = (
            ui.input(
                "Current Password",
                password=True,
                password_toggle_button=True,
            )
            .props('aria-label="Current Password"')
            .classes("w-full")
        )
        new_input = (
            ui.input(
                "New Password",
                password=True,
                password_toggle_button=True,
            )
            .props('aria-label="New Password"')
            .classes("w-full")
        )
        confirm_input = (
            ui.input(
                "Confirm New Password",
                password=True,
                password_toggle_button=True,
            )
            .props('aria-label="Confirm New Password"')
            .classes("w-full")
        )
        status_label = ui.label("").classes("text-xs text-red-400")

        def _submit_rotation() -> None:
            cur_val = str(current_input.value or "")
            new_val = str(new_input.value or "")
            conf_val = str(confirm_input.value or "")
            if not cur_val or not new_val:
                status_label.text = "Current and new passwords are required."
                return
            if new_val != conf_val:
                status_label.text = "New passwords do not match."
                return
            if len(new_val) < 8:
                status_label.text = "New password must be at least 8 characters."
                return
            try:
                auth_manager.rotate_password(
                    identity.user_id,
                    SecretStr(cur_val),
                    SecretStr(new_val),
                )
            except HTTPException as exc:
                status_label.text = str(exc.detail)
                return
            ui.notify("Password updated.", type="positive")
            dialog.close()

        confirm_input.on("keydown.enter", _submit_rotation)
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Cancel", on_click=dialog.close).props(
                'color="grey-8" aria-label="Cancel password change"'
            )
            ui.button("Update Password", on_click=_submit_rotation).props(
                'color="primary" aria-label="Confirm password change"'
            )

    dialog.open()


__all__ = [
    "open_change_password_dialog",
    "render_login_panel",
    "resolve_session_identity",
]
