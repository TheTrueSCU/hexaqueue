"""Unit tests for `hq auth rotate-password` CLI command."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from hexaqueue_cli.commands import auth as auth_cmd
from hexaqueue_cli.main import app


def test_cli_auth_rotate_password_prompts_and_masks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify CLI prompts for existing password and confirmed new password."""
    captured: dict[str, object] = {}

    def fake_rotate(
        username: str,
        current_secret: SecretStr,
        new_secret: SecretStr,
        *,
        dashboard_url: str | None = None,
        offline: bool = False,
    ) -> str:
        captured["username"] = username
        captured["current"] = current_secret.get_secret_value()
        captured["new"] = new_secret.get_secret_value()
        captured["url"] = dashboard_url
        captured["offline"] = offline
        return f"Rotated password for '{username}' offline in SQLite"

    monkeypatch.setattr(auth_cmd, "rotate_dashboard_password", fake_rotate)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["auth", "rotate-password", "--user", "rjdw", "--offline"],
        input="old-pass\nnew-pass\nnew-pass\n",
    )

    exit_code = result.exit_code
    assert exit_code == 0
    assert captured["username"] == "rjdw"
    assert captured["current"] == "old-pass"
    assert captured["new"] == "new-pass"
    assert captured["offline"] is True
    assert "old-pass" not in result.output
    assert "new-pass" not in result.output


def test_cli_auth_rotate_password_error_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify rotation errors exit with status code 1 without leaking secrets."""

    def failing_rotate(*_args: object, **_kwargs: object) -> str:
        raise ValueError("Current password verification failed.")

    monkeypatch.setattr(auth_cmd, "rotate_dashboard_password", failing_rotate)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["auth", "rotate-password"],
        input="bad-pass\nnew-pass\nnew-pass\n",
    )

    exit_code = result.exit_code
    assert exit_code == 1
    assert "Current password verification failed." in result.output
