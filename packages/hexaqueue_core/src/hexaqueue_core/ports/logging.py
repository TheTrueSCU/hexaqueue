"""Log streaming and telemetry port interfaces.

Notes/Architectural Intent:
    Provides chunked log capture and real-time pub/sub distribution
    for `hq logs -f` and web dashboard observers without blocking task execution.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LogChunk(BaseModel):
    """Chunk of log output emitted by a running job.

    Args:
        job_id: Unique job identifier.
        stream: Source stream ('stdout' or 'stderr').
        content: Text chunk payload.
        offset: Byte offset or line sequence counter.
        timestamp: ISO 8601 UTC timestamp.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str = Field(description="Log line or chunk text payload")
    job_id: str = Field(description="Job identifier")
    offset: int = Field(ge=0, description="Chunk byte or sequence offset")
    stream: str = Field(
        default="stdout", description="Stream identifier ('stdout'/'stderr')"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Chunk emit timestamp"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate log chunk invariants."""
        if not self.job_id.strip():
            msg = "job_id cannot be empty"
            raise ValueError(msg)
        if self.stream not in ("stdout", "stderr", "system"):
            msg = f"stream must be 'stdout', 'stderr', or 'system', got '{self.stream}'"
            raise ValueError(msg)
        return self


class LogStreamPort(ABC):
    """Abstract port interface for writing and streaming job execution logs."""

    @abstractmethod
    async def write_log(self, chunk: LogChunk) -> None:
        """Append a log chunk to the job's log buffer.

        Args:
            chunk: LogChunk to append.
        """

    @abstractmethod
    def stream_logs(
        self, job_id: str, follow: bool = False, tail: int | None = None
    ) -> AsyncIterator[LogChunk]:
        """Stream log chunks for a given job.

        Args:
            job_id: Job identifier to tail.
            follow: If True, keep stream open and yield new chunks in real-time.
            tail: Optional line limit for historical logs.

        Yields:
            LogChunk instances in chronological order.
        """
