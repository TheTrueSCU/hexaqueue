"""Domain models for interactive pseudo-terminal (PTY) attach sessions.

Notes/Architectural Intent:
    Defines request contracts, resize events, and metadata for `hq exec` and `hq attach`
    bidirectional interactive sessions into active jobs.
"""

from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PtySessionRequest(BaseModel):
    """Specification for requesting an interactive PTY session.

    Args:
        session_id: Unique identifier for this terminal session.
        job_id: Identifier of the target running job.
        user_id: Identity of the requesting actor.
        roles: List of RBAC security roles assigned to user.
        command: Command and arguments to execute within PTY (e.g. ['/bin/bash']).
        rows: Initial terminal row count.
        cols: Initial terminal column count.
        term_type: Terminal capability emulation type (e.g. 'xterm-256color').
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cols: int = Field(default=80, ge=1, le=1000, description="Terminal columns")
    command: list[str] = Field(
        default_factory=lambda: ["/bin/bash"],
        description="Command vector to spawn",
    )
    job_id: str = Field(description="Target job identifier")
    roles: list[str] = Field(
        default_factory=list, description="Actor RBAC security roles"
    )
    rows: int = Field(default=24, ge=1, le=1000, description="Terminal rows")
    session_id: str = Field(description="Unique interactive session identifier")
    term_type: str = Field(
        default="xterm-256color", description="TERM environment variable string"
    )
    user_id: str = Field(description="Requesting user identifier")

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate non-empty identifiers."""
        if not self.session_id.strip():
            msg = "session_id cannot be empty"
            raise ValueError(msg)
        if not self.job_id.strip():
            msg = "job_id cannot be empty"
            raise ValueError(msg)
        if not self.user_id.strip():
            msg = "user_id cannot be empty"
            raise ValueError(msg)
        if not self.command:
            msg = "command vector cannot be empty"
            raise ValueError(msg)
        return self


class PtyResizeEvent(BaseModel):
    """Terminal window resize notification (SIGWINCH).

    Args:
        session_id: Unique interactive session identifier.
        rows: New terminal row count.
        cols: New terminal column count.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cols: int = Field(ge=1, le=1000, description="Updated terminal columns")
    rows: int = Field(ge=1, le=1000, description="Updated terminal rows")
    session_id: str = Field(description="Interactive session identifier")


class PtySessionInfo(BaseModel):
    """Metadata describing an active or completed PTY session.

    Args:
        session_id: Unique session identifier.
        job_id: Target job identifier.
        user_id: Requesting user identifier.
        pid: Process identifier of the spawned shell.
        is_active: Whether the interactive process is currently alive.
        created_at: Session establishment timestamp.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Session creation timestamp",
    )
    is_active: bool = Field(
        default=True, description="Whether session process is alive"
    )
    job_id: str = Field(description="Target job identifier")
    pid: int = Field(ge=1, description="Spawned process ID")
    session_id: str = Field(description="Unique session identifier")
    user_id: str = Field(description="User who created session")


__all__ = [
    "PtyResizeEvent",
    "PtySessionInfo",
    "PtySessionRequest",
]
