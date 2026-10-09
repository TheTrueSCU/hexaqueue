"""Configuration settings for cluster monitoring and budget accounting daemon.

Notes/Architectural Intent:
    Defines configurable interval thresholds for worker node pulse tracking,
    liveness failure detection, and automatic stale reservation reclamation.
"""

from pydantic import BaseModel, ConfigDict, Field


class MonitorConfig(BaseModel):
    """Configuration options for the cluster monitor and budget accountant daemon.

    Args:
        dead_threshold_seconds: Seconds without heartbeat before worker is marked DEAD.
        heartbeat_interval_seconds: Recommended polling or pulse emission interval in seconds.
        reaper_interval_seconds: Periodic interval in seconds between dead node and expiry sweep runs.
        reservation_expiry_seconds: Maximum age of an unfinalized budget hold before expiration.
        unhealthy_threshold_seconds: Seconds without heartbeat before worker is marked UNHEALTHY.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dead_threshold_seconds: float = Field(
        default=60.0,
        ge=0.0,
        description="Seconds without heartbeat before worker is marked DEAD",
    )
    heartbeat_interval_seconds: float = Field(
        default=10.0,
        ge=0.0,
        description="Heartbeat pulse interval in seconds",
    )
    reaper_interval_seconds: float = Field(
        default=15.0,
        ge=0.0,
        description="Interval in seconds between reaper sweeps",
    )
    reservation_expiry_seconds: float = Field(
        default=3600.0,
        ge=0.0,
        description="Maximum lifetime in seconds for unfinalized budget holds",
    )
    unhealthy_threshold_seconds: float = Field(
        default=30.0,
        ge=0.0,
        description="Seconds without heartbeat before worker is marked UNHEALTHY",
    )


__all__ = [
    "MonitorConfig",
]
