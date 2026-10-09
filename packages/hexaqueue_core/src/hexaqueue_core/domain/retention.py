"""Domain models for storage lifecycle and differential log retention policies.

Notes/Architectural Intent:
    Defines differential retention windows and cloud storage lifecycle tags
    for terminal job execution artifacts and logs. Succeeded runs are kept briefly
    to conserve storage budget, whereas failed runs are preserved longer with
    diagnostic dumps for post-mortem engineering triage.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_core.domain.lifecycle import TerminalOutcome


class LogRetentionTier(StrEnum):
    """Classification tier for execution log storage lifecycle."""

    SHORT_PASS = "SHORT_PASS"  # noqa: S105
    LONG_FAIL = "LONG_FAIL"


class LogRetentionPolicy(BaseModel):
    """Policy specifying log expiration lifetime and cloud object tags.

    Args:
        tier: Retention tier classification.
        ttl_days: Storage retention window in days.
        tag_key: Cloud object metadata tag key.
        tag_value: Cloud object metadata tag value.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tier: LogRetentionTier = Field(description="Retention tier classification")
    ttl_days: int = Field(gt=0, description="Retention window in days")
    tag_key: str = Field(default="Retention", description="Object metadata key")
    tag_value: str = Field(
        description="Object metadata value (e.g. ShortPass, LongFail)"
    )

    @classmethod
    def for_outcome(cls, outcome: TerminalOutcome) -> "LogRetentionPolicy":
        """Resolve differential retention policy based on terminal job outcome.

        Args:
            outcome: TerminalOutcome of the finished job.

        Returns:
            LogRetentionPolicy with appropriate TTL and cloud lifecycle tags.

        Notes/Architectural Intent:
            COMPLETED jobs receive SHORT_PASS (14 days default).
            FAILED, TIMED_OUT, CANCELLED, or PREEMPTED jobs receive LONG_FAIL (90 days default).
        """
        if outcome == TerminalOutcome.COMPLETED:
            return cls(
                tier=LogRetentionTier.SHORT_PASS,
                ttl_days=14,
                tag_value="ShortPass",
            )
        return cls(
            tier=LogRetentionTier.LONG_FAIL,
            ttl_days=90,
            tag_value="LongFail",
        )


__all__ = [
    "LogRetentionPolicy",
    "LogRetentionTier",
]
