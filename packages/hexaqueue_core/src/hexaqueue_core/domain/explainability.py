"""Domain models and engine for scheduler explainability and decision reporting.

Notes/Architectural Intent:
    Provides transparent diagnostic models and explainability calculations to solve
    the 'black-box' batch scheduler problem. Exposes priority breakdowns, queue rankings,
    detailed blocker causes, and hierarchical fair-share inspection reports.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from hexaqueue_core.domain.fairshare import FairShareNode, FairShareTree
from hexaqueue_core.domain.job import JobSpec, JobState
from hexaqueue_core.domain.priority import JobPriorityCalculator
from hexaqueue_core.domain.scheduling import ResourceSlotPool


class PendingReasonCode(StrEnum):
    """Categorized root causes for why a job is waiting in pending state."""

    BLOCKED_BY_DEPENDENCY = "BLOCKED_BY_DEPENDENCY"
    BLOCKED_BY_PRIORITY_ANCHOR = "BLOCKED_BY_PRIORITY_ANCHOR"
    CLUSTER_SATURATED = "CLUSTER_SATURATED"
    FAIRSHARE_THROTTLE = "FAIRSHARE_THROTTLE"
    INSUFFICIENT_CLUSTER_CAPACITY = "INSUFFICIENT_CLUSTER_CAPACITY"
    READY = "READY"
    WAITING_FOR_GRACE_PERIOD = "WAITING_FOR_GRACE_PERIOD"


class PendingReason(BaseModel):
    """Structured explanation and metadata for a pending scheduling blocker."""

    code: PendingReasonCode = Field(description="Normalized diagnostic reason code")
    message: str = Field(description="Human-readable explanation of the condition")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Diagnostic parameters and metrics"
    )


class PriorityBreakdown(BaseModel):
    """Granular multi-factor priority score calculation breakdown."""

    base_score: float = Field(description="Base priority weight contribution")
    age_score: float = Field(description="Aging factor weight contribution")
    fairshare_score: float = Field(description="Fair-share factor weight contribution")
    preemption_bonus: float = Field(
        description="Compensatory priority boost from prior interruption"
    )
    total_priority: float = Field(
        description="Combined effective priority score used for ranking"
    )
    age_seconds: float = Field(description="Total seconds job has waited in queue")
    fairshare_factor: float = Field(
        description="Dynamic Slurm/LSF fair-share factor F in (0.0, 1.0]"
    )
    target_share: float = Field(description="Normalized target share entitlement")
    actual_usage: float = Field(description="Decayed cumulative historical usage")


class SchedulingDecisionReport(BaseModel):
    """Complete diagnostic report explaining the scheduling status of a job."""

    job_id: str = Field(description="Target job identifier")
    user: str = Field(description="Job owner identifier or pseudonym")
    state: JobState = Field(description="Current job lifecycle state")
    queue_position: int = Field(
        description="1-indexed rank among pending jobs (0 if not pending)"
    )
    queue_total: int = Field(
        description="Total count of pending jobs evaluated in queue"
    )
    priority_breakdown: PriorityBreakdown = Field(
        description="Detailed priority component scores"
    )
    pending_reasons: list[PendingReason] = Field(
        default_factory=list, description="Ordered list of blocking factors"
    )
    blocking_anchor_id: str | None = Field(
        default=None, description="Job ID of higher-priority anchor holding reservation"
    )
    required_slots: int = Field(default=1, description="Slots required to run")
    available_slots: int = Field(
        default=0, description="Slots currently free in cluster"
    )
    total_slots: int = Field(default=0, description="Total cluster slot capacity")
    estimated_wait_seconds: float | None = Field(
        default=None, description="Estimated wait until execution start"
    )
    summary: str = Field(
        description="Concise one-liner summary of why the job is pending or running"
    )
    is_redacted: bool = Field(
        default=False, description="Whether sensitive fields have been sanitized"
    )


class FairShareNodeReport(BaseModel):
    """Diagnostic node in a hierarchical fair-share inspection tree."""

    id: str = Field(description="User or account identifier")
    parent_id: str | None = Field(default=None, description="Parent account ID")
    shares: float = Field(description="Configured raw share weight")
    target_share: float = Field(description="Normalized target share fraction")
    raw_usage: float = Field(description="Un-decayed historical usage consumed")
    decayed_usage: float = Field(
        description="Exponentially decayed resource usage metric"
    )
    fairshare_factor: float = Field(description="Calculated fair-share factor F")
    children: list["FairShareNodeReport"] = Field(
        default_factory=list, description="Sub-accounts or child users"
    )


class FairShareTreeReport(BaseModel):
    """Full hierarchical fair-share inspection report."""

    root: FairShareNodeReport = Field(description="Root fair-share tree node")
    half_life_seconds: float = Field(description="Usage decay half-life in seconds")
    total_decayed_usage: float = Field(
        description="Total system decayed resource usage"
    )


class SchedulerExplainabilityEngine:
    """Engine computing scheduling diagnostics, priority breakdowns, and explainability.

    Notes/Architectural Intent:
        Operates purely over domain models (JobSpec, FairShareTree, ResourceSlotPool)
        to evaluate queue placement, priority math, and blocker diagnostics without
        coupling to persistence or networking layers.
    """

    def __init__(
        self,
        priority_calculator: JobPriorityCalculator | None = None,
        fairshare_tree: FairShareTree | None = None,
        default_job_duration: float = 60.0,
    ) -> None:
        """Initialize explainability engine.

        Args:
            priority_calculator: Calculator for multi-factor priority scoring.
            fairshare_tree: Hierarchical fair-share tree.
            default_job_duration: Fallback duration estimate in seconds.
        """
        self._priority = priority_calculator or JobPriorityCalculator()
        self._fairshare = fairshare_tree or FairShareTree()
        self._default_job_duration = default_job_duration

    def explain_job(
        self,
        job_id: str,
        all_jobs: list[JobSpec],
        pool: ResourceSlotPool,
        current_timestamp: float,
    ) -> SchedulingDecisionReport:
        """Generate a complete explainability report for a target job.

        Args:
            job_id: Target job identifier.
            all_jobs: All jobs known in current cycle (pending and running).
            pool: Cluster resource slot pool.
            current_timestamp: Evaluation timestamp in seconds.

        Returns:
            SchedulingDecisionReport detailing placement, priority math, and blockers.

        Raises:
            ValueError: If job_id is not found in all_jobs.
        """
        target_job: JobSpec | None = None
        for j in all_jobs:
            if j.id == job_id:
                target_job = j
                break

        if target_job is None:
            raise ValueError(f"Job with id '{job_id}' not found")

        # Compute fair-share factors across all active users
        user_ids = {j.user for j in all_jobs}
        factors = {
            uid: self._fairshare.compute_fairshare_factor(uid, current_timestamp)
            for uid in user_ids
        }

        # Filter and rank pending jobs (including newly submitted jobs)
        pending_jobs = [
            j
            for j in all_jobs
            if j.status.state in (JobState.PENDING, JobState.SUBMITTED)
        ]
        ranked_pending = self._priority.rank_jobs(
            jobs=pending_jobs,
            current_timestamp=current_timestamp,
            fairshare_factors=factors,
        )

        queue_position = 0
        queue_total = len(ranked_pending)
        for idx, ranked in enumerate(ranked_pending, start=1):
            if ranked.job.id == job_id:
                queue_position = idx
                break

        # Compute priority breakdown for target job
        breakdown = self._compute_breakdown(
            target_job=target_job,
            current_timestamp=current_timestamp,
            user_factors=factors,
        )

        # Detect pending blocker reasons
        pending_reasons, blocking_anchor_id, summary = self._evaluate_blockers(
            target_job=target_job,
            queue_position=queue_position,
            ranked_pending=ranked_pending,
            pool=pool,
            breakdown=breakdown,
        )

        required_slots = max(1, target_job.resources.cpus)
        return SchedulingDecisionReport(
            job_id=target_job.id,
            user=target_job.user,
            state=target_job.status.state,
            queue_position=queue_position,
            queue_total=queue_total,
            priority_breakdown=breakdown,
            pending_reasons=pending_reasons,
            blocking_anchor_id=blocking_anchor_id,
            required_slots=required_slots,
            available_slots=pool.available_slots,
            total_slots=pool.total_slots,
            estimated_wait_seconds=self._estimate_wait(queue_position),
            summary=summary,
            is_redacted=False,
        )

    def explain_fairshare(self, current_timestamp: float) -> FairShareTreeReport:
        """Generate a complete diagnostic report of the fair-share tree hierarchy.

        Args:
            current_timestamp: Evaluation timestamp for usage decay calculation.

        Returns:
            FairShareTreeReport containing the hierarchical tree structure.
        """
        root_node = self._fairshare.root
        total_decayed = self._fairshare.total_decayed_usage(current_timestamp)
        normalized_shares = self._fairshare.compute_normalized_shares()

        def _build_node_report(node: FairShareNode) -> FairShareNodeReport:
            factor = self._fairshare.compute_fairshare_factor(
                node.id, current_timestamp
            )
            target_share = normalized_shares.get(node.id, 0.0)
            children = [
                _build_node_report(child)
                for child in self._fairshare.get_children(node.id)
            ]
            return FairShareNodeReport(
                id=node.id,
                parent_id=node.parent_id,
                shares=node.shares,
                target_share=round(target_share, 4),
                raw_usage=round(node.historical_usage, 2),
                decayed_usage=round(node.historical_usage, 2),
                fairshare_factor=round(factor, 4),
                children=children,
            )

        root_report = _build_node_report(root_node)
        return FairShareTreeReport(
            root=root_report,
            half_life_seconds=self._fairshare.half_life_seconds,
            total_decayed_usage=round(total_decayed, 3),
        )

    def _compute_breakdown(
        self,
        target_job: JobSpec,
        current_timestamp: float,
        user_factors: dict[str, float],
    ) -> PriorityBreakdown:
        """Compute detailed priority component scores for a job."""
        created_ts = target_job.created_at.timestamp()
        wait_seconds = max(0.0, current_timestamp - created_ts)
        age_factor = min(1.0, wait_seconds / self._priority.weights.max_age_seconds)
        fs_factor = user_factors.get(target_job.user, 1.0)

        weights = self._priority.weights
        age_score = weights.weight_age * age_factor
        fairshare_score = weights.weight_fairshare * fs_factor
        base_score = weights.weight_base_priority * float(target_job.priority)
        bonus = target_job.priority_bonus
        total = age_score + fairshare_score + base_score + bonus

        node = self._fairshare.get_node(target_job.user)
        normalized_shares = self._fairshare.compute_normalized_shares()
        target_share = normalized_shares.get(target_job.user, 1.0)
        raw_usage = node.historical_usage if node else 0.0

        return PriorityBreakdown(
            base_score=round(base_score, 2),
            age_score=round(age_score, 2),
            fairshare_score=round(fairshare_score, 2),
            preemption_bonus=round(bonus, 2),
            total_priority=round(total, 2),
            age_seconds=round(wait_seconds, 1),
            fairshare_factor=round(fs_factor, 4),
            target_share=round(target_share, 4),
            actual_usage=round(raw_usage, 2),
        )

    def _evaluate_blockers(
        self,
        target_job: JobSpec,
        queue_position: int,
        ranked_pending: list[Any],
        pool: ResourceSlotPool,
        breakdown: PriorityBreakdown,
    ) -> tuple[list[PendingReason], str | None, str]:
        """Determine specific pending blockers and generate summary sentence."""
        if target_job.status.state not in (JobState.PENDING, JobState.SUBMITTED):
            return (
                [],
                None,
                f"Job '{target_job.id}' is in state {target_job.status.state}.",
            )

        reasons: list[PendingReason] = []
        blocking_anchor_id: str | None = None
        req_slots = max(1, target_job.resources.cpus)

        # Check total cluster limit
        if req_slots > pool.total_slots:
            reasons.append(
                PendingReason(
                    code=PendingReasonCode.INSUFFICIENT_CLUSTER_CAPACITY,
                    message=(
                        f"Requires {req_slots} slots, but cluster total capacity is "
                        f"{pool.total_slots} slots."
                    ),
                    details={"required": req_slots, "total_slots": pool.total_slots},
                )
            )

        # Check anchor reservation
        if queue_position > 1:
            anchor_job = ranked_pending[0].job
            blocking_anchor_id = anchor_job.id
            reasons.append(
                PendingReason(
                    code=PendingReasonCode.BLOCKED_BY_PRIORITY_ANCHOR,
                    message=(
                        f"Queue rank #{queue_position}: Blocked by higher-priority job "
                        f"'{anchor_job.id}' (User: '{anchor_job.user}')."
                    ),
                    details={
                        "anchor_id": anchor_job.id,
                        "anchor_user": anchor_job.user,
                    },
                )
            )

        # Check cluster saturation
        if pool.available_slots < req_slots:
            reasons.append(
                PendingReason(
                    code=PendingReasonCode.CLUSTER_SATURATED,
                    message=(
                        f"Cluster busy: requires {req_slots} slots, but only "
                        f"{pool.available_slots} slots currently available."
                    ),
                    details={"required": req_slots, "available": pool.available_slots},
                )
            )

        # Check fairshare throttle if factor is significantly depleted (< 0.5)
        if breakdown.fairshare_factor < 0.5:
            reasons.append(
                PendingReason(
                    code=PendingReasonCode.FAIRSHARE_THROTTLE,
                    message=(
                        f"User '{target_job.user}' fair-share factor is "
                        f"{breakdown.fairshare_factor:.3f} (<0.500) due to high recent usage."
                    ),
                    details={
                        "fairshare_factor": breakdown.fairshare_factor,
                        "actual_usage": breakdown.actual_usage,
                    },
                )
            )

        # Build concise summary
        if not reasons:
            reasons.append(
                PendingReason(
                    code=PendingReasonCode.READY,
                    message="Job is at top of queue and ready for dispatch.",
                )
            )
            summary = f"Job '{target_job.id}' is ready for immediate dispatch."
        else:
            primary = reasons[0].message
            summary = f"Rank #{queue_position} of {len(ranked_pending)}: {primary}"

        return reasons, blocking_anchor_id, summary

    def _estimate_wait(self, queue_position: int) -> float | None:
        """Estimate waiting time until dispatch based on queue position."""
        if queue_position <= 1:
            return 0.0
        return (queue_position - 1) * self._default_job_duration


__all__ = [
    "FairShareNodeReport",
    "FairShareTreeReport",
    "PendingReason",
    "PendingReasonCode",
    "PriorityBreakdown",
    "SchedulerExplainabilityEngine",
    "SchedulingDecisionReport",
]
