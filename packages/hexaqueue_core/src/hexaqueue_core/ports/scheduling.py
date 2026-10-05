"""Batch scheduling engine port interface.

Notes/Architectural Intent:
    Defines the abstract interface for multi-factor batch schedulers,
    decoupling lifecycle controllers from concrete priority aging algorithms,
    backfill policies, and preemption strategies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.scheduling import SchedulingDecision


class BatchSchedulerPort(ABC):
    """Abstract port interface for batch scheduler implementations."""

    @abstractmethod
    def schedule_cycle(
        self,
        pending_jobs: list[JobSpec],
        running_jobs: list[JobSpec],
        current_timestamp: float,
        estimated_durations: dict[str, float] | None = None,
    ) -> SchedulingDecision:
        """Execute a batch scheduling evaluation cycle.

        Args:
            pending_jobs: Unscheduled jobs currently waiting in queue.
            running_jobs: Jobs actively executing in the cluster.
            current_timestamp: Evaluation timestamp in seconds.
            estimated_durations: Optional estimated runtime per job for backfill calculation.

        Returns:
            SchedulingDecision containing dispatches, preemptions, and queue states.
        """

    @abstractmethod
    def record_job_start(self, job_id: str, timestamp: float) -> None:
        """Record execution start time for runtime tracking.

        Args:
            job_id: Identifier of the started job.
            timestamp: Execution start timestamp.
        """

    @abstractmethod
    def record_job_completion(
        self, job: JobSpec, timestamp: float, duration_seconds: float
    ) -> None:
        """Record job completion and update historical resource consumption.

        Args:
            job: Completed JobSpec.
            timestamp: Completion timestamp.
            duration_seconds: Wall-clock duration consumed.
        """


__all__ = [
    "BatchSchedulerPort",
]
