"""Local pseudo-terminal (PTY) interactive bridge adapter.

Notes/Architectural Intent:
    Allocates POSIX pseudo-terminals (PTY master/slave pairs) to host interactive
    attach sessions (`hq exec` / `hq attach`). Validates strict RBAC ownership
    and operator roles before spawning interactive shells.
"""

import asyncio
import contextlib
import fcntl
import os
import pty
import struct
import termios
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Final

from hexaqueue_worker.domain.pty import PtySessionInfo, PtySessionRequest
from hexaqueue_worker.ports.pty import InteractivePtyPort

DEFAULT_ALLOWED_ROLES: Final[frozenset[str]] = frozenset(
    {"admin", "cluster-admin", "operator"}
)


@dataclass
class _ActivePtySession:
    info: PtySessionInfo
    master_fd: int
    proc: asyncio.subprocess.Process
    output_queue: asyncio.Queue[bytes | None]
    loop: asyncio.AbstractEventLoop


class LocalPtyBridgeAdapter(InteractivePtyPort):
    """Local execution host PTY bridge adapter.

    Notes/Architectural Intent:
        Uses `loop.add_reader` on the PTY master file descriptor for reactive,
        zero-polling terminal chunk multiplexing directly into client streams.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _ActivePtySession] = {}
        self._lock = asyncio.Lock()

    def _validate_rbac(self, request: PtySessionRequest, job_owner: str) -> None:
        """Enforce role-based access control for interactive sessions."""
        is_owner = request.user_id.strip() == job_owner.strip()
        has_elevated_role = any(
            role.strip().casefold() in DEFAULT_ALLOWED_ROLES for role in request.roles
        )
        if not (is_owner or has_elevated_role):
            msg = (
                f"User '{request.user_id}' lacks permission to attach to job "
                f"'{request.job_id}' owned by '{job_owner}'."
            )
            raise PermissionError(msg)

    def _set_window_size(self, fd: int, rows: int, cols: int) -> None:
        """Configure terminal window dimensions."""
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

    async def create_session(
        self, request: PtySessionRequest, job_owner: str = "default"
    ) -> PtySessionInfo:
        """Create an interactive terminal session inside a target job environment.

        Args:
            request: PtySessionRequest specification.
            job_owner: Identity of the job's owning user for RBAC validation.

        Returns:
            PtySessionInfo describing the created session.

        Raises:
            PermissionError: If user_id does not match job_owner and lacks admin/operator role.
        """
        self._validate_rbac(request, job_owner)

        master_fd, slave_fd = pty.openpty()
        self._set_window_size(master_fd, request.rows, request.cols)

        env = os.environ.copy()
        env["TERM"] = request.term_type

        try:
            proc = await asyncio.create_subprocess_exec(
                *request.command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=env,
                close_fds=True,
            )
        finally:
            os.close(slave_fd)

        os.set_blocking(master_fd, False)
        output_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=1000)
        loop = asyncio.get_running_loop()

        def _on_readable() -> None:
            try:
                data = os.read(master_fd, 4096)
                if not data:
                    loop.remove_reader(master_fd)
                    output_queue.put_nowait(None)
                    return
                output_queue.put_nowait(data)
            except (BlockingIOError, InterruptedError):
                pass
            except OSError:
                with contextlib.suppress(Exception):
                    loop.remove_reader(master_fd)
                output_queue.put_nowait(None)

        loop.add_reader(master_fd, _on_readable)

        info = PtySessionInfo(
            session_id=request.session_id,
            job_id=request.job_id,
            user_id=request.user_id,
            pid=proc.pid,
            is_active=True,
        )

        session = _ActivePtySession(
            info=info,
            master_fd=master_fd,
            proc=proc,
            output_queue=output_queue,
            loop=loop,
        )

        async with self._lock:
            self._sessions[request.session_id] = session

        return info

    async def write_stdin(self, session_id: str, data: bytes) -> None:
        """Write stdin bytes to the interactive terminal session.

        Args:
            session_id: Session identifier.
            data: Raw input bytes (keystrokes, escapes, EOF).
        """
        async with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return
        with contextlib.suppress(OSError):
            os.write(session.master_fd, data)

    async def read_stdout(self, session_id: str) -> AsyncIterator[bytes]:
        """Stream stdout bytes from the pseudo-terminal master.

        Args:
            session_id: Session identifier.

        Yields:
            Raw terminal output bytes.
        """
        async with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return

        while True:
            chunk = await session.output_queue.get()
            if chunk is None:
                break
            yield chunk

    async def resize(self, session_id: str, rows: int, cols: int) -> None:
        """Propagate terminal window resize (SIGWINCH) to the session.

        Args:
            session_id: Session identifier.
            rows: Terminal height in rows.
            cols: Terminal width in columns.
        """
        async with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return
        with contextlib.suppress(OSError):
            self._set_window_size(session.master_fd, rows, cols)

    async def terminate_session(self, session_id: str) -> None:
        """Gracefully close and clean up an active PTY session.

        Args:
            session_id: Session identifier.
        """
        async with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return

        with contextlib.suppress(Exception):
            session.loop.remove_reader(session.master_fd)

        with contextlib.suppress(Exception):
            os.close(session.master_fd)

        if session.proc.returncode is None:
            session.proc.terminate()
            try:
                await asyncio.wait_for(session.proc.wait(), timeout=1.0)
            except TimeoutError:
                session.proc.kill()
                await session.proc.wait()

        session.output_queue.put_nowait(None)


__all__ = [
    "DEFAULT_ALLOWED_ROLES",
    "LocalPtyBridgeAdapter",
]
