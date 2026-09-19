"""Port interface for interactive pseudo-terminal (PTY) attach sessions.

Notes/Architectural Intent:
    Defines the contract for establishing bidirectional interactive terminal streams
    (stdout, stderr, stdin, window resize events) inside running compute tasks.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from hexaqueue_worker.domain.pty import PtySessionInfo, PtySessionRequest


class InteractivePtyPort(ABC):
    """Abstract port interface for managing interactive PTY sessions."""

    @abstractmethod
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

    @abstractmethod
    async def write_stdin(self, session_id: str, data: bytes) -> None:
        """Write stdin bytes to the interactive terminal session.

        Args:
            session_id: Session identifier.
            data: Raw input bytes (keystrokes, escapes, EOF).
        """

    @abstractmethod
    def read_stdout(self, session_id: str) -> AsyncIterator[bytes]:
        """Stream stdout bytes from the pseudo-terminal master.

        Args:
            session_id: Session identifier.

        Yields:
            Raw terminal output bytes.
        """

    @abstractmethod
    async def resize(self, session_id: str, rows: int, cols: int) -> None:
        """Propagate terminal window resize (SIGWINCH) to the session.

        Args:
            session_id: Session identifier.
            rows: Terminal height in rows.
            cols: Terminal width in columns.
        """

    @abstractmethod
    async def terminate_session(self, session_id: str) -> None:
        """Gracefully close and clean up an active PTY session.

        Args:
            session_id: Session identifier.
        """


__all__ = [
    "InteractivePtyPort",
]
