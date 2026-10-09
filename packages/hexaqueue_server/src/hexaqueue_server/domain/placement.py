"""Tiered worker pool and warm cache affinity placement engine.

Notes/Architectural Intent:
    Evaluates worker node candidates across provisioning tiers (STATIC vs EPHEMERAL)
    and Content-Addressable Storage (CAS) warm cache contents to optimize job dispatching,
    minimize network bundle fetch overhead, and trigger cloud bursting when needed.
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.node import (
    ComputeNodeProfile,
    NodeHealthState,
    NodeProvisioningTier,
)


class PlacementDecision(BaseModel):
    """Result of a worker node placement evaluation.

    Args:
        hit_ratio: Proportion of required collateral present in node cache [0.0, 1.0].
        reason: Justification explanation for the placement decision.
        selected_node_id: Chosen compute worker node ID, or None if unscheduled.
        should_burst_ephemeral: True if static capacity is exhausted and cloud bursting is advised.
        tier: Provisioning tier of the selected node.
        total_required: Total count of required collateral hashes.
        warm_hits: Count of required collateral hashes pre-cached on selected node.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hit_ratio: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Warm cache hit ratio [0.0, 1.0]",
    )
    reason: str = Field(description="Decision justification")
    selected_node_id: str | None = Field(
        default=None, description="Selected worker node identifier"
    )
    should_burst_ephemeral: bool = Field(
        default=False,
        description="Whether dynamic ephemeral worker bursting is recommended",
    )
    tier: NodeProvisioningTier | None = Field(
        default=None, description="Provisioning tier of selected node"
    )
    total_required: int = Field(
        default=0, ge=0, description="Total required collateral bundles"
    )
    warm_hits: int = Field(default=0, ge=0, description="Pre-cached collateral bundles")


class WarmCachePlacementEngine:
    """Calculates compute node placement with warm cache affinity and tiered fallback.

    Notes/Architectural Intent:
        Implements Issue #16 placement strategy:
        1. Prioritize healthy STATIC nodes with 100% warm collateral cache hits.
        2. Prefer STATIC nodes with partial warm cache hits.
        3. Fall back to clean/idle STATIC nodes (lowest current job concurrency).
        4. Fall back to active EPHEMERAL burst nodes.
        5. If all nodes are saturated and queue backlog >= burst_backlog_threshold,
           recommend dynamic ephemeral bursting (`should_burst_ephemeral=True`).
    """

    def __init__(self, burst_backlog_threshold: int = 5) -> None:
        """Initialize warm cache placement engine.

        Args:
            burst_backlog_threshold: Minimum queue backlog to trigger ephemeral burst recommendation.
        """
        self._burst_threshold = max(1, burst_backlog_threshold)

    @property
    def burst_backlog_threshold(self) -> int:
        """Configured backlog threshold for ephemeral bursting."""
        return self._burst_threshold

    def evaluate_placement(
        self,
        job: JobSpec,
        nodes: Sequence[ComputeNodeProfile],
        collateral_hash_map: dict[str, str] | None = None,
        backlog_size: int = 0,
    ) -> PlacementDecision:
        """Evaluate candidate nodes and determine optimal placement for a job.

        Args:
            job: Candidate JobSpec to place.
            nodes: Sequence of currently registered ComputeNodeProfile records.
            collateral_hash_map: Optional mapping of collateral IDs to CAS SHA-256 hashes.
            backlog_size: Number of waiting jobs currently queued in the backlog.

        Returns:
            PlacementDecision indicating selected node or burst recommendation.

        Notes/Architectural Intent:
            Ensures deterministic, zero-copy scheduling favoring permanent nodes
            with pre-warmed disk caches before spending cloud budget on ephemeral VMs.
        """
        # 1. Filter healthy candidate nodes with available slot capacity
        eligible: list[ComputeNodeProfile] = []
        for node in nodes:
            if node.health_state != NodeHealthState.HEALTHY:
                continue
            if node.capacity is not None:
                needed_cpus = max(1, job.resources.cpus)
                if node.capacity.available_cpus < needed_cpus:
                    continue
            eligible.append(node)

        # 2. Resolve required collateral bundle hashes
        hash_map = collateral_hash_map or {}
        required_hashes = {hash_map.get(cid, cid) for cid in job.collateral_ids}
        total_req = len(required_hashes)

        # 3. Partition eligible nodes by provisioning tier
        static_candidates = [
            n for n in eligible if n.tier == NodeProvisioningTier.STATIC
        ]
        ephemeral_candidates = [
            n for n in eligible if n.tier == NodeProvisioningTier.EPHEMERAL
        ]

        def _node_affinity_key(node: ComputeNodeProfile) -> tuple[int, int, str]:
            hits = len(required_hashes & node.cached_collateral_hashes)
            load = len(node.active_job_ids)
            # More hits is better (-hits), lower load is better (+load), deterministic tiebreak (+node_id)
            return (-hits, load, node.node_id)

        # 4. Check STATIC candidates first
        if static_candidates:
            static_candidates.sort(key=_node_affinity_key)
            best_static = static_candidates[0]
            hits = len(required_hashes & best_static.cached_collateral_hashes)
            ratio = (hits / total_req) if total_req > 0 else 1.0
            reason = (
                f"Selected STATIC node '{best_static.node_id}' with {hits}/{total_req} "
                f"warm cache hits ({ratio:.0%}) and {len(best_static.active_job_ids)} active jobs."
            )
            return PlacementDecision(
                hit_ratio=ratio,
                reason=reason,
                selected_node_id=best_static.node_id,
                should_burst_ephemeral=False,
                tier=NodeProvisioningTier.STATIC,
                total_required=total_req,
                warm_hits=hits,
            )

        # 5. Check EPHEMERAL candidates next
        if ephemeral_candidates:
            ephemeral_candidates.sort(key=_node_affinity_key)
            best_ephemeral = ephemeral_candidates[0]
            hits = len(required_hashes & best_ephemeral.cached_collateral_hashes)
            ratio = (hits / total_req) if total_req > 0 else 1.0
            reason = (
                f"Selected EPHEMERAL node '{best_ephemeral.node_id}' with {hits}/{total_req} "
                f"warm cache hits ({ratio:.0%})."
            )
            return PlacementDecision(
                hit_ratio=ratio,
                reason=reason,
                selected_node_id=best_ephemeral.node_id,
                should_burst_ephemeral=False,
                tier=NodeProvisioningTier.EPHEMERAL,
                total_required=total_req,
                warm_hits=hits,
            )

        # 6. Saturated cluster: evaluate auto-scaling dynamic cloud burst trigger
        if backlog_size >= self._burst_threshold:
            reason = (
                f"Static and ephemeral pools saturated; queue backlog ({backlog_size}) "
                f"exceeds threshold ({self._burst_threshold}). Recommend dynamic cloud bursting."
            )
            return PlacementDecision(
                hit_ratio=0.0,
                reason=reason,
                selected_node_id=None,
                should_burst_ephemeral=True,
                tier=None,
                total_required=total_req,
                warm_hits=0,
            )

        reason = (
            "All registered compute nodes are currently at maximum capacity. "
            "Job retained in priority queue awaiting node slot release."
        )
        return PlacementDecision(
            hit_ratio=0.0,
            reason=reason,
            selected_node_id=None,
            should_burst_ephemeral=False,
            tier=None,
            total_required=total_req,
            warm_hits=0,
        )


__all__ = [
    "PlacementDecision",
    "WarmCachePlacementEngine",
]
