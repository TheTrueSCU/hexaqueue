"""Unit tests for `hq dashboard` tunnel and browser CLI commands."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from hexaqueue_cli.commands import dashboard as dashboard_cmd
from hexaqueue_cli.main import app


def test_cli_dashboard_tunnel_and_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify tunnel start/status/stop and `hq dashboard open` behavior."""
    state = {"active": False, "opened_url": ""}

    def fake_start(**_kwargs: object) -> bool:
        was_active = state["active"]
        state["active"] = True
        return not was_active

    def fake_active(**_kwargs: object) -> bool:
        return bool(state["active"])

    def fake_stop(**_kwargs: object) -> bool:
        was_active = bool(state["active"])
        state["active"] = False
        return was_active

    def fake_browser(url: str) -> bool:
        state["opened_url"] = url
        return True

    monkeypatch.setattr(dashboard_cmd, "start_tunnel", fake_start)
    monkeypatch.setattr(dashboard_cmd, "is_tunnel_active", fake_active)
    monkeypatch.setattr(dashboard_cmd, "stop_tunnel", fake_stop)
    monkeypatch.setattr(dashboard_cmd.webbrowser, "open", fake_browser)

    runner = CliRunner()
    res_status_0 = runner.invoke(app, ["dashboard", "tunnel", "status"])
    assert res_status_0.exit_code == 0
    assert "INACTIVE" in res_status_0.output

    res_start = runner.invoke(app, ["dashboard", "tunnel", "start"])
    assert res_start.exit_code == 0
    assert "Started dashboard tunnel" in res_start.output

    res_status_1 = runner.invoke(app, ["dashboard", "tunnel", "status"])
    assert res_status_1.exit_code == 0
    assert "ACTIVE" in res_status_1.output

    res_open = runner.invoke(app, ["dashboard", "open", "--local-port", "8080"])
    assert res_open.exit_code == 0
    assert state["opened_url"] == "http://127.0.0.1:8080/dashboard/ui"

    res_stop = runner.invoke(app, ["dashboard", "tunnel", "stop"])
    assert res_stop.exit_code == 0
    assert "Stopped dashboard SSH tunnel" in res_stop.output
