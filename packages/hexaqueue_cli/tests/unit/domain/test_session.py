"""Tests for CLI session manager."""

import pytest

from hexaqueue_cli.domain.session import (
    LocalCliSession,
    get_default_session,
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
