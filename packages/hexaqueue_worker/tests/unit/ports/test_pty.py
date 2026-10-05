"""Unit tests for InteractivePtyPort interface contracts."""

from collections.abc import AsyncIterator

import pytest

from hexaqueue_worker.domain.pty import PtySessionInfo, PtySessionRequest
from hexaqueue_worker.ports.pty import InteractivePtyPort


class DummyInteractivePtyAdapter(InteractivePtyPort):
    """Test double implementing InteractivePtyPort."""

    def __init__(self) -> None:
        self.sessions: dict[str, PtySessionInfo] = {}

    async def create_session(
        self, request: PtySessionRequest, job_owner: str = "default"
    ) -> PtySessionInfo:
        """Create mock session."""
        info = PtySessionInfo(
            session_id=request.session_id,
            job_id=request.job_id,
            user_id=request.user_id,
            pid=9999,
        )
        self.sessions[request.session_id] = info
        return info

    async def write_stdin(self, session_id: str, data: bytes) -> None:
        """Mock write."""
        _ = (session_id, data)

    async def read_stdout(self, session_id: str) -> AsyncIterator[bytes]:
        """Mock read."""
        yield b"mock output\n"

    async def resize(self, session_id: str, rows: int, cols: int) -> None:
        """Mock resize."""
        _ = (session_id, rows, cols)

    async def terminate_session(self, session_id: str) -> None:
        """Mock terminate."""
        self.sessions.pop(session_id, None)


@pytest.mark.asyncio
async def test_interactive_pty_port_contract() -> None:
    """Verify InteractivePtyPort dummy implementation contract."""
    adapter = DummyInteractivePtyAdapter()
    req = PtySessionRequest(
        session_id="s1",
        job_id="j1",
        user_id="user1",
    )
    info = await adapter.create_session(req)
    pid = info.pid
    assert pid == 9999
    chunks = [c async for c in adapter.read_stdout("s1")]
    assert len(chunks) == 1
    assert chunks[0] == b"mock output\n"
    await adapter.terminate_session("s1")
    assert "s1" not in adapter.sessions
