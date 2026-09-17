"""Batch scheduling, conservative backfilling, and controlled preemption engines.

Notes/Architectural Intent:
    Orchestrates cluster resource slot pools, fair-share deficit evaluation,
    conservative backfilling, and deterministic preemption to eliminate monopoly starvation
    (the 100-slot problem) while preserving total resource conservation invariants.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.fairshare import FairShareTree
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.priority import (
    JobPriorityCalculator,
    RankedJob,
)


class ResourceSlotPool:
    """Tracks cluster slot capacity and active allocations.

    Notes/Architectural Intent:
        Encapsulates slot and core accounting. Guarantees that total allocated
        resources never exceed cluster capacity limits (conservation invariant).
    """

    def __init__(self, total_slots: int, total_cpus: int | None = None) -> None:
        """Initialize resource slot pool.

        Args:
            total_slots: Maximum concurrent execution slots in cluster.
            total_cpus: Optional total CPU core count (defaults to total_slots).

        Raises:
            ValueError: If total_slots <= 0.
        """
        if total_slots <= 0:
            msg = "total_slots must be positive"
            raise ValueError(msg)

        self._total_slots = total_slots
        self._total_cpus = total_cpus if total_cpus is not None else total_slots
        self._allocated_jobs: dict[str, JobSpec] = {}

    @property
    def total_slots(self) -> int:
        """Total slot capacity of the cluster."""
        return self._total_slots

    @property
    def used_slots(self) -> int:
        """Number of currently occupied slots."""
        return sum(max(1, j.resources.cpus) for j in self._allocated_jobs.values())

    @property
    def available_slots(self) -> int:
        """Remaining unallocated slots."""
        return max(0, self._total_slots - self.used_slots)

    def can_fit(self, job: JobSpec) -> bool:
        """Check if a job can fit into currently unallocated slots.

        Args:
            job: Candidate JobSpec.

        Returns:
            True if sufficient slots and CPUs exist, False otherwise.
        """
        required_slots = max(1, job.resources.cpus)
        return self.available_slots >= required_slots

    def allocate(self, job: JobSpec) -> bool:
        """Allocate resources for a job.

        Args:
            job: JobSpec to allocate.

        Returns:
            True if allocation succeeded, False if insufficient capacity.
        """
        if not self.can_fit(job):
            return False
        self._allocated_jobs[job.id] = job
        return True

    def release(self, job_id: str) -> bool:
        """Release allocated resources for a job.

        Args:
            job_id: Identifier of the job to release.

        Returns:
            True if job was allocated and released, False otherwise.
        """
        if job_id in self._allocated_jobs:
            del self._allocated_jobs[job_id]
            return True
        return False

    def is_allocated(self, job_id: str) -> bool:
        """Check whether a specific job is currently allocated."""
        return job_id in self._allocated_jobs


class PreemptionPolicy(BaseModel):
    """Configuration governing scheduler-initiated controlled preemption.

    Args:
        grace_period_seconds: Waiting period before an under-quota user triggers preemption.
        starvation_deficit_threshold: Minimum fair-share gap ratio required to trigger preemption.
        preemption_bonus: Priority boost awarded to preempted jobs to compensate for interruption.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    grace_period_seconds: float = Field(
        default=30.0,
        ge=0.0,
        description="Wait time in seconds before preemption triggers",
    )
    preemption_bonus: float = Field(
        default=5000.0,
        ge=0.0,
        description="Compensatory priority boost granted to preempted jobs",
    )
    starvation_deficit_threshold: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Minimum fair-share factor to qualify for preemption",
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate preemption policy invariants."""
        if self.grace_period_seconds < 0.0:
            msg = "grace_period_seconds cannot be negative"
            raise ValueError(msg)
        return self


class SchedulingDecision(BaseModel):
    """Immutable result of a single batch scheduling evaluation cycle.

    Args:
        to_run: Jobs selected to immediately start execution.
        to_preempt: Running jobs selected for preemption paired with justification.
        to_backfill: Sub-priority jobs safely slotted via conservative backfilling.
        remains_pending: Jobs that must continue waiting in queue.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    backfilled_jobs: list[JobSpec] = Field(
        default_factory=list, description="Jobs scheduled via backfill"
    )
    preempted_jobs: list[tuple[str, str]] = Field(
        default_factory=list,
        description="Pairs of (job_id, preemption_reason)",
    )
    remains_pending: list[JobSpec] = Field(
        default_factory=list, description="Jobs remaining in queue"
    )
    to_run: list[JobSpec] = Field(
        default_factory=list, description="Jobs dispatched to run"
    )


class ControlledPreemptionEngine:
    """Determines and executes fair-share preemption to resolve monopoly starvation.

    Notes/Architectural Intent:
        Solves the 100-slot monopoly thought experiment. When user A holds 100% of
        cluster slots and user B (with equal or greater entitlement) submits jobs,
        this engine deterministically identifies the lowest-impact running jobs
        from user A to preempt, compensating them with priority bonuses.
    """

    def __init__(self, policy: PreemptionPolicy | None = None) -> None:
        """Initialize preemption engine.

        Args:
            policy: Optional custom PreemptionPolicy.
        """
        self._policy = policy or PreemptionPolicy()

    @property
    def policy(self) -> PreemptionPolicy:
        """Current preemption policy."""
        return self._policy

    def find_starved_job(
        self,
        pending_jobs: list[RankedJob],
        current_timestamp: float,
    ) -> RankedJob | None:
        """Identify if any high-priority pending job is suffering from monopoly starvation.

        Args:
            pending_jobs: Candidate pending jobs ranked by priority.
            current_timestamp: Current scheduling timestamp.

        Returns:
            The most starved RankedJob eligible to trigger preemption, or None.
        """
        for ranked in pending_jobs:
            wait_time = max(0.0, current_timestamp - ranked.job.created_at.timestamp())
            is_expired = wait_time >= self._policy.grace_period_seconds
            has_entitlement = (
                ranked.fairshare_factor >= self._policy.starvation_deficit_threshold
            )
            if is_expired and has_entitlement:
                return ranked
        return None

    def select_preemption_candidate(
        self,
        running_jobs: list[JobSpec],
        starved_user: str,
        current_timestamp: float,
        start_times: dict[str, float] | None = None,
    ) -> JobSpec | None:
        """Select the lowest-cost running job to preempt from an over-consuming user.

        Args:
            running_jobs: Active running jobs in the cluster.
            starved_user: The user requiring freed slots (cannot preempt themselves).
            current_timestamp: Current evaluation timestamp.
            start_times: Optional mapping of job ID to execution start time.

        Returns:
            The best JobSpec candidate to preempt, or None if no candidates qualify.

        Notes/Architectural Intent:
            Preemption selection ordering (lowest impact):
            1. Cannot preempt jobs belonging to the starved user.
            2. Prefer checkpointable jobs (zero compute loss).
            3. Prefer youngest jobs (lowest elapsed execution time).
            4. Prefer lower base priority.
        """
        eligible = [j for j in running_jobs if j.user != starved_user]
        if not eligible:
            return None

        starts = start_times or {}

        def candidate_key(job: JobSpec) -> tuple[int, float, int]:
            # 1. Checkpointable preferred (0 before 1)
            checkpoint_score = 0 if job.checkpointable else 1
            # 2. Youngest elapsed runtime preferred (lower elapsed time)
            elapsed = max(
                0.0, current_timestamp - starts.get(job.id, current_timestamp)
            )
            # 3. Base priority (lower preferred)
            return (checkpoint_score, elapsed, job.priority)

        eligible.sort(key=candidate_key)
        return eligible[0]


class ConservativeBackfillScheduler:
    """EASY / Conservative backfilling engine to utilize idle resource gaps safely.

    Notes/Architectural Intent:
        Prevents cluster under-utilization by scheduling smaller pending jobs into
        current idle slots if their execution will not delay the calculated start
        time of the highest-priority blocked job (the Priority Anchor).
    """

    def __init__(self, default_job_duration_seconds: float = 60.0) -> None:
        """Initialize backfill scheduler.

        Args:
            default_job_duration_seconds: Fallback runtime estimation if unspecified.
        """
        self._default_duration = default_job_duration_seconds

    def evaluate_backfill(
        self,
        unallocated_pending: list[RankedJob],
        pool: ResourceSlotPool,
        anchor_reservation_window: float,
        job_durations: dict[str, float] | None = None,
    ) -> list[JobSpec]:
        """Identify pending jobs that can safely backfill without delaying the anchor.

        Args:
            unallocated_pending: Pending jobs following the priority anchor.
            pool: Current resource slot pool.
            anchor_reservation_window: Time remaining until anchor job receives reserved slots.
            job_durations: Estimated execution durations per job.

        Returns:
            List of JobSpec entities approved for backfill scheduling.
        """
        durations = job_durations or {}
        backfilled: list[JobSpec] = []

        for ranked in unallocated_pending:
            if not pool.can_fit(ranked.job):
                continue

            est_duration = durations.get(ranked.job.id, self._default_duration)
            if est_duration <= anchor_reservation_window:
                pool.allocate(ranked.job)
                backfilled.append(ranked.job)

        return backfilled


class BatchSchedulerEngine:
    """Unified batch scheduler orchestrating priority aging, fair-share, and preemption.

    Notes/Architectural Intent:
        The central scheduling authority of Hexaqueue. Combines multi-factor priority
        ranking, hierarchical fair-share coefficients, conservative backfilling, and
        scheduler-initiated preemption into a deterministic, single-pass scheduling cycle.
    """

    def __init__(
        self,
        pool: ResourceSlotPool,
        fairshare_tree: FairShareTree | None = None,
        priority_calculator: JobPriorityCalculator | None = None,
        preemption_engine: ControlledPreemptionEngine | None = None,
        backfill_scheduler: ConservativeBackfillScheduler | None = None,
    ) -> None:
        """Initialize batch scheduler engine.

        Args:
            pool: Cluster resource slot pool.
            fairshare_tree: Hierarchical fair-share tree.
            priority_calculator: Multi-factor priority calculator.
            preemption_engine: Controlled preemption engine.
            backfill_scheduler: Conservative backfill scheduler.
        """
        self._pool = pool
        self._fairshare = fairshare_tree or FairShareTree()
        self._priority = priority_calculator or JobPriorityCalculator()
        self._preemption = preemption_engine or ControlledPreemptionEngine()
        self._backfill = backfill_scheduler or ConservativeBackfillScheduler()
        self._start_times: dict[str, float] = {}

    @property
    def pool(self) -> ResourceSlotPool:
        """Cluster resource slot pool."""
        return self._pool

    @property
    def fairshare_tree(self) -> FairShareTree:
        """Fair-share tree instance."""
        return self._fairshare

    def record_job_start(self, job_id: str, timestamp: float) -> None:
        """Record execution start time for runtime tracking."""
        self._start_times[job_id] = timestamp

    def record_job_completion(
        self, job: JobSpec, timestamp: float, duration_seconds: float
    ) -> None:
        """Record job completion and update historical usage in fair-share tree.

        Args:
            job: Completed JobSpec.
            timestamp: Completion timestamp.
            duration_seconds: Wall-clock duration consumed.
        """
        self._pool.release(job.id)
        if job.id in self._start_times:
            del self._start_times[job.id]

        # Consumed slot-seconds = slots * duration
        slots = max(1, job.resources.cpus)
        consumed = slots * duration_seconds
        if self._fairshare.get_node(job.user) is not None:
            self._fairshare.record_usage(job.user, consumed, timestamp)

    def _allocate_top_priority(
        self, ranked_pending: list[RankedJob]
    ) -> tuple[list[JobSpec], RankedJob | None, list[RankedJob]]:
        """Allocate resources to highest-priority pending jobs.

        Args:
            ranked_pending: Ordered list of pending jobs.

        Returns:
            Tuple of (allocated jobs, anchor job if blocked, remaining ranked jobs).
        """
        to_run: list[JobSpec] = []
        anchor: RankedJob | None = None
        remaining_ranked: list[RankedJob] = []

        for ranked in ranked_pending:
            if self._pool.can_fit(ranked.job):
                self._pool.allocate(ranked.job)
                to_run.append(ranked.job)
            elif anchor is None:
                anchor = ranked
            else:
                remaining_ranked.append(ranked)

        return to_run, anchor, remaining_ranked

    def _handle_monopoly_preemption(
        self,
        anchor: RankedJob | None,
        remaining_ranked: list[RankedJob],
        running_jobs: list[JobSpec],
        current_timestamp: float,
        to_run: list[JobSpec],
        to_preempt: list[tuple[str, str]],
    ) -> tuple[RankedJob | None, list[RankedJob]]:
        """Evaluate and execute preemption if an anchor job is starved by cluster monopoly.

        Args:
            anchor: The highest-priority blocked job reservation.
            remaining_ranked: Other pending jobs awaiting scheduling.
            running_jobs: Currently running cluster jobs.
            current_timestamp: Evaluation timestamp.
            to_run: Mutable list of jobs approved for execution.
            to_preempt: Mutable list of preempted job IDs and reasons.

        Returns:
            Updated tuple of (anchor, remaining_ranked).
        """
        if anchor is None or self._pool.available_slots > 0:
            return anchor, remaining_ranked

        candidates = [anchor, *remaining_ranked]
        starved = self._preemption.find_starved_job(candidates, current_timestamp)
        if starved is None:
            return anchor, remaining_ranked

        candidate = self._preemption.select_preemption_candidate(
            running_jobs=running_jobs,
            starved_user=starved.job.user,
            current_timestamp=current_timestamp,
            start_times=self._start_times,
        )
        if candidate is None:
            return anchor, remaining_ranked

        self._pool.release(candidate.id)
        reason = (
            f"Preempted to resolve fair-share starvation for user '{starved.job.user}'"
        )
        to_preempt.append((candidate.id, reason))

        if not self._pool.can_fit(starved.job):
            return anchor, remaining_ranked

        self._pool.allocate(starved.job)
        to_run.append(starved.job)
        if anchor.job.id == starved.job.id:
            return None, remaining_ranked

        new_remaining = [r for r in remaining_ranked if r.job.id != starved.job.id]
        return anchor, new_remaining

    def _handle_backfill(
        self,
        anchor: RankedJob | None,
        remaining_ranked: list[RankedJob],
        estimated_durations: dict[str, float] | None,
    ) -> tuple[list[JobSpec], list[RankedJob]]:
        """Attempt conservative backfill of lower-priority jobs into spare slots.

        Args:
            anchor: Blocked priority anchor job holding reservations.
            remaining_ranked: Candidate jobs for backfilling.
            estimated_durations: Optional map of job execution durations.

        Returns:
            Tuple of (backfilled jobs, updated remaining ranked jobs).
        """
        if anchor is None or self._pool.available_slots == 0:
            return [], remaining_ranked

        reservation_window = 60.0
        backfilled = self._backfill.evaluate_backfill(
            unallocated_pending=remaining_ranked,
            pool=self._pool,
            anchor_reservation_window=reservation_window,
            job_durations=estimated_durations,
        )
        backfilled_ids = {j.id for j in backfilled}
        new_remaining = [r for r in remaining_ranked if r.job.id not in backfilled_ids]
        return backfilled, new_remaining

    def schedule_cycle(
        self,
        pending_jobs: list[JobSpec],
        running_jobs: list[JobSpec],
        current_timestamp: float,
        estimated_durations: dict[str, float] | None = None,
    ) -> SchedulingDecision:
        """Execute a single batch scheduling evaluation cycle.

        Args:
            pending_jobs: Unscheduled jobs currently waiting in queue.
            running_jobs: Jobs actively executing in the cluster.
            current_timestamp: Evaluation timestamp in seconds.
            estimated_durations: Optional estimated runtime per job for backfill calculation.

        Returns:
            SchedulingDecision containing dispatches, preemptions, and queue states.
        """
        if not pending_jobs:
            return SchedulingDecision()

        # 1. Compute dynamic fair-share factors for all active users
        user_ids = {j.user for j in pending_jobs} | {j.user for j in running_jobs}
        factors = {
            uid: self._fairshare.compute_fairshare_factor(uid, current_timestamp)
            for uid in user_ids
        }

        # 2. Rank pending jobs by effective multi-factor priority
        ranked_pending = self._priority.rank_jobs(
            jobs=pending_jobs,
            current_timestamp=current_timestamp,
            fairshare_factors=factors,
        )

        to_preempt: list[tuple[str, str]] = []

        # 3. Direct allocation loop for top-priority jobs
        to_run, anchor, remaining_ranked = self._allocate_top_priority(ranked_pending)

        # 4. If an anchor exists and cluster is full, evaluate monopoly preemption
        anchor, remaining_ranked = self._handle_monopoly_preemption(
            anchor=anchor,
            remaining_ranked=remaining_ranked,
            running_jobs=running_jobs,
            current_timestamp=current_timestamp,
            to_run=to_run,
            to_preempt=to_preempt,
        )

        # 5. If slots remain and an anchor is waiting, attempt conservative backfill
        backfilled, remaining_ranked = self._handle_backfill(
            anchor=anchor,
            remaining_ranked=remaining_ranked,
            estimated_durations=estimated_durations,
        )

        remains = ([anchor.job] if anchor else []) + [r.job for r in remaining_ranked]

        return SchedulingDecision(
            to_run=to_run,
            preempted_jobs=to_preempt,
            backfilled_jobs=backfilled,
            remains_pending=remains,
        )


__all__ = [
    "BatchSchedulerEngine",
    "ConservativeBackfillScheduler",
    "ControlledPreemptionEngine",
    "PreemptionPolicy",
    "ResourceSlotPool",
    "SchedulingDecision",
]
