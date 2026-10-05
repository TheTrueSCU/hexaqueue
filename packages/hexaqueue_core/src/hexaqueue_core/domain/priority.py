"""Multi-factor dynamic priority aging engine for queue scheduling.

Notes/Architectural Intent:
    Combines waiting time (age factor), fair-share historical entitlement,
    user-assigned baseline priority, and preemption compensation bonuses into
    a single deterministic scalar priority. Prevents queue starvation of low-priority
    jobs via monotonic age ramping while preserving organizational fair-share policy.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.job import JobSpec


class PriorityWeights(BaseModel):
    """Configurable weights for multi-factor priority calculation.

    Args:
        weight_age: Relative weight of waiting time in queue.
        weight_fairshare: Relative weight of fair-share deficit/surplus factor.
        weight_base_priority: Multiplier for user-specified baseline priority.
        max_age_seconds: Time horizon in seconds at which age factor saturates to 1.0.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_age_seconds: float = Field(
        default=86400.0,
        gt=0.0,
        description="Elapsed wait time at which age factor reaches 1.0",
    )
    weight_age: float = Field(default=1000.0, ge=0.0, description="Aging weight factor")
    weight_base_priority: float = Field(
        default=10.0, ge=0.0, description="Base user priority multiplier"
    )
    weight_fairshare: float = Field(
        default=10000.0, ge=0.0, description="Fair-share entitlement weight factor"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate priority weights invariants."""
        if (
            self.weight_age == 0.0
            and self.weight_fairshare == 0.0
            and self.weight_base_priority == 0.0
        ):
            msg = "At least one priority weight must be non-zero"
            raise ValueError(msg)
        return self


class RankedJob(BaseModel):
    """Job decorated with decomposed scheduling factors and calculated effective priority.

    Args:
        job: Underlying JobSpec instance.
        effective_priority: Aggregated scalar priority used for queue ordering.
        age_factor: Normalized wait time contribution in range [0.0, 1.0].
        fairshare_factor: Normalized fair-share entitlement contribution in range [0.0, 1.0].
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    age_factor: float = Field(ge=0.0, le=1.0, description="Normalized age factor")
    effective_priority: float = Field(description="Aggregated scheduling priority")
    fairshare_factor: float = Field(
        ge=0.0, le=1.0, description="Normalized fair-share factor"
    )
    job: JobSpec = Field(description="Underlying job specification")


class JobPriorityCalculator:
    """Calculates multi-factor dynamic priorities and orders queued workloads.

    Notes/Architectural Intent:
        Encapsulates pure priority math. Given a snapshot of job attributes,
        submission timestamps, and fair-share coefficients, deterministically
        computes effective priorities and sorts queues with stable tie-breaking.
    """

    def __init__(self, weights: PriorityWeights | None = None) -> None:
        """Initialize calculator with priority weights.

        Args:
            weights: Optional custom PriorityWeights configuration.
        """
        self._weights = weights or PriorityWeights()

    @property
    def weights(self) -> PriorityWeights:
        """Current priority weights configuration."""
        return self._weights

    def calculate_effective_priority(
        self,
        job: JobSpec,
        current_timestamp: float,
        fairshare_factor: float = 1.0,
    ) -> tuple[float, float]:
        """Compute effective priority and age factor for a single job.

        Args:
            job: Target JobSpec.
            current_timestamp: Unix epoch timestamp in seconds.
            fairshare_factor: Calculated fair-share coefficient in [0.0, 1.0].

        Returns:
            Tuple of (effective_priority, age_factor).

        Notes/Architectural Intent:
            Priority = (W_age * AgeFactor) + (W_fairshare * FairShareFactor)
                     + (W_base * BasePriority) + PriorityBonus
        """
        wait_seconds = max(0.0, current_timestamp - job.created_at.timestamp())
        age_factor = min(1.0, wait_seconds / self._weights.max_age_seconds)

        prio = (
            (self._weights.weight_age * age_factor)
            + (self._weights.weight_fairshare * fairshare_factor)
            + (self._weights.weight_base_priority * float(job.priority))
            + job.priority_bonus
        )
        return float(prio), float(age_factor)

    def rank_jobs(
        self,
        jobs: list[JobSpec],
        current_timestamp: float,
        fairshare_factors: dict[str, float] | None = None,
    ) -> list[RankedJob]:
        """Rank and sort a batch of candidate jobs by descending effective priority.

        Args:
            jobs: Collection of candidate JobSpec entities.
            current_timestamp: Unix epoch timestamp for age calculation.
            fairshare_factors: Optional mapping from user ID to fairshare factor.

        Returns:
            List of RankedJob instances sorted from highest to lowest priority.

        Notes/Architectural Intent:
            Tie-breaking is strictly deterministic:
            1. Effective priority (descending)
            2. Creation timestamp (ascending, FIFO for equal priority)
            3. Job identifier (casefold ascending)
        """
        factors = fairshare_factors or {}
        ranked: list[RankedJob] = []

        for job in jobs:
            fs_factor = factors.get(job.user, 1.0)
            prio, age_factor = self.calculate_effective_priority(
                job=job,
                current_timestamp=current_timestamp,
                fairshare_factor=fs_factor,
            )
            ranked.append(
                RankedJob(
                    job=job,
                    effective_priority=prio,
                    age_factor=age_factor,
                    fairshare_factor=fs_factor,
                )
            )

        ranked.sort(
            key=lambda r: (
                -r.effective_priority,
                r.job.created_at.timestamp(),
                r.job.id,
            )
        )
        return ranked


__all__ = [
    "JobPriorityCalculator",
    "PriorityWeights",
    "RankedJob",
]
