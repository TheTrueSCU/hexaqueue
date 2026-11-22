"""Tests for CLI session manager."""

import pytest

from hexaqueue_cli.domain.session import (
    LocalCliSession,
    get_active_controller_url,
    get_default_session,
    resolve_controller_url,
    set_active_controller_url,
    set_default_session,
)


@pytest.mark.asyncio
async def test_cli_session_lifecycle() -> None:
    """Verify CLI session initialization and lifecycle."""
    session = LocalCliSession(concurrency=2)
    assert session.queue is not None
    assert session.controller is not None
    assert session.worker is not None

    await session.start()
    await session.stop()


def test_default_session_get_set() -> None:
    """Verify getting and setting default global session."""
    s1 = get_default_session()
    assert s1 is not None

    custom = LocalCliSession(concurrency=1)
    set_default_session(custom)
    assert get_default_session() is custom

    set_default_session(None)


def test_controller_url_resolution_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify explicit > active callback > HEXAQUEUE_CONTROLLER_URL > HEXAQUEUE_URL > None."""
    set_active_controller_url(None)
    monkeypatch.delenv("HEXAQUEUE_CONTROLLER_URL", raising=False)
    monkeypatch.delenv("HEXAQUEUE_URL", raising=False)

    assert get_active_controller_url() is None
    assert resolve_controller_url() is None

    monkeypatch.setenv("HEXAQUEUE_URL", "http://env-url:8000/")
    res_env_url = resolve_controller_url()
    assert res_env_url == "http://env-url:8000"

    monkeypatch.setenv("HEXAQUEUE_CONTROLLER_URL", "http://ctrl-url:8000/")
    res_ctrl_url = resolve_controller_url()
    assert res_ctrl_url == "http://ctrl-url:8000"

    set_active_controller_url(" http://callback-url:8000/ ")
    res_active = get_active_controller_url()
    assert res_active == "http://callback-url:8000"
    res_cb = resolve_controller_url()
    assert res_cb == "http://callback-url:8000"

    res_explicit = resolve_controller_url("http://explicit:9000/")
    assert res_explicit == "http://explicit:9000"

    set_active_controller_url("   ")
    assert get_active_controller_url() is None
    set_active_controller_url(None)
