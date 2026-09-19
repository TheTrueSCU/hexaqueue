"""Unit tests for LocalPtyBridgeAdapter."""

import pytest

from hexaqueue_worker.adapters.pty import LocalPtyBridgeAdapter
from hexaqueue_worker.domain.pty import PtySessionRequest


@pytest.mark.asyncio
async def test_pty_rbac_unauthorized() -> None:
    """Verify unauthorized user cannot create interactive PTY session."""
    bridge = LocalPtyBridgeAdapter()
    req = PtySessionRequest(
        session_id="sess-unauth",
        job_id="job-target",
        user_id="mallory",
        roles=["guest"],
    )
    with pytest.raises(PermissionError, match="lacks permission to attach"):
        await bridge.create_session(req, job_owner="alice")


@pytest.mark.asyncio
async def test_pty_rbac_admin_authorized() -> None:
    """Verify administrator can attach to any job interactive session."""
    bridge = LocalPtyBridgeAdapter()
    req = PtySessionRequest(
        session_id="sess-admin",
        job_id="job-target",
        user_id="bob",
        roles=["admin"],
        command=["/bin/echo", "admin_session"],
    )
    info = await bridge.create_session(req, job_owner="alice")
    try:
        pid = info.pid
        assert pid > 0
        u_id = info.user_id
        assert u_id == "bob"
    finally:
        await bridge.terminate_session("sess-admin")


@pytest.mark.asyncio
async def test_pty_session_lifecycle_and_io() -> None:
    """Verify session creation, output streaming, resize, and termination."""
    bridge = LocalPtyBridgeAdapter()
    req = PtySessionRequest(
        session_id="sess-io",
        job_id="job-io",
        user_id="alice",
        roles=[],
        command=["/bin/sh", "-c", "echo 'hello_from_pty' && sleep 0.1"],
    )
    info = await bridge.create_session(req, job_owner="alice")
    pid = info.pid
    assert pid > 0

    await bridge.resize("sess-io", rows=35, cols=90)
    await bridge.write_stdin("sess-io", b"\n")

    chunks: list[bytes] = []
    async for chunk in bridge.read_stdout("sess-io"):
        chunks.append(chunk)

    all_output = b"".join(chunks).decode("utf-8", errors="replace")
    assert "hello_from_pty" in all_output

    await bridge.terminate_session("sess-io")


@pytest.mark.asyncio
async def test_pty_unknown_session_operations() -> None:
    """Verify operations on non-existent session fail safely without raising errors."""
    bridge = LocalPtyBridgeAdapter()
    await bridge.write_stdin("non-existent", b"test")
    await bridge.resize("non-existent", rows=24, cols=80)
    await bridge.terminate_session("non-existent")

    chunks = [c async for c in bridge.read_stdout("non-existent")]
    assert chunks == []
