"""Distributed leader election and lease coordination domain models.

Notes/Architectural Intent:
    Defines time-bounded leader leases used by active/standby central controllers
    to coordinate cluster operations and prevent split-brain execution.
"""

from datetime import UTC, datetime, timedelta
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LeaderLease(BaseModel):
    """Time-bounded lease granting exclusive active leadership to a controller.

    Args:
        leader_id: Unique candidate or node identifier holding the lease.
        lease_duration_seconds: Duration in seconds for which the lease is valid.
        acquired_at: Timestamp in UTC when leadership was initially acquired.
        expires_at: Timestamp in UTC after which the lease is considered expired.
        renewal_count: Number of successful heartbeat renewals performed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    acquired_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Lease acquisition timestamp in UTC",
    )
    expires_at: datetime = Field(description="Lease expiration timestamp in UTC")
    leader_id: str = Field(description="Active leader identifier")
    lease_duration_seconds: float = Field(
        gt=0.0, description="Lease validity duration in seconds"
    )
    renewal_count: int = Field(
        default=0, ge=0, description="Number of heartbeat renewals"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate required identifier fields and expiration ordering.

        Returns:
            The validated LeaderLease instance.

        Raises:
            ValueError: If leader_id is blank or expires_at is before acquired_at.
        """
        if not self.leader_id.strip():
            msg = "leader_id cannot be empty"
            raise ValueError(msg)
        if self.expires_at < self.acquired_at:
            msg = f"expires_at ({self.expires_at}) cannot precede acquired_at ({self.acquired_at})"
            raise ValueError(msg)
        return self

    def is_expired(self, now: datetime | None = None) -> bool:
        """Check whether the lease has passed its expiration deadline.

        Args:
            now: Optional point-in-time timestamp (defaults to current UTC time).

        Returns:
            True if the lease is expired, False otherwise.
        """
        current_time = now or datetime.now(UTC)
        return current_time >= self.expires_at

    def renew(self, duration_seconds: float | None = None) -> Self:
        """Extend the lease expiration by the specified or existing duration.

        Args:
            duration_seconds: Optional new validity duration in seconds.

        Returns:
            Updated LeaderLease instance with extended expiration.
        """
        now = datetime.now(UTC)
        duration = duration_seconds or self.lease_duration_seconds
        new_expires = now + timedelta(seconds=duration)
        return self.model_copy(
            update={
                "expires_at": new_expires,
                "lease_duration_seconds": duration,
                "renewal_count": self.renewal_count + 1,
            }
        )


__all__ = [
    "LeaderLease",
]
