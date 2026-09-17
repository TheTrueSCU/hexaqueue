"""Hierarchical Fair-Share Tree and continuous decay models.

Notes/Architectural Intent:
    Implements multi-level fair-share tree balancing (Root -> Department -> Team -> User)
    with continuous exponential half-life decay. Balances cluster entitlement against historical
    compute consumption using standard Slurm/LSF fair-tree mathematical formulations.
"""

from __future__ import annotations

import math
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FairShareNode(BaseModel):
    """A node in the hierarchical fair-share tree representing an entity's entitlement and usage.

    Args:
        id: Unique identifier for the department, team, or user account.
        parent_id: Optional parent node identifier in the tree hierarchy.
        shares: Target entitlement weight relative to sibling nodes (must be > 0).
        historical_usage: Accumulated, decayed compute resource usage (slot-seconds or cpu-seconds).
        last_decay_timestamp: Unix epoch timestamp when decay was last applied to this node.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Unique entity identifier")
    parent_id: str | None = Field(
        default=None, description="Parent node identifier in the hierarchy"
    )
    shares: float = Field(
        default=1.0, gt=0.0, description="Entitlement share weight relative to siblings"
    )
    historical_usage: float = Field(
        default=0.0, ge=0.0, description="Decayed historical compute usage"
    )
    last_decay_timestamp: float = Field(
        default=0.0, ge=0.0, description="Timestamp of last decay evaluation"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate fair-share node domain invariants."""
        if not self.id.strip():
            msg = "FairShareNode id cannot be empty"
            raise ValueError(msg)
        return self


class FairShareTree:
    """Hierarchical tree orchestrator for fair-share entitlement and decay evaluation.

    Notes/Architectural Intent:
        Encapsulates tree traversal, normalized share distribution down branches,
        and continuous half-life decay. Guarantees deterministic computation of
        fair-share priority factors across all hierarchy levels.
    """

    def __init__(self, root_id: str = "root") -> None:
        """Initialize fair-share tree with a designated root node.

        Args:
            root_id: Unique identifier of the root organizational node.
        """
        self._nodes: dict[str, FairShareNode] = {}
        self._children: dict[str, list[str]] = {}
        self._root_id = root_id
        self.add_node(FairShareNode(id=root_id, parent_id=None, shares=1.0))

    @property
    def root_id(self) -> str:
        """Identifier of the root node."""
        return self._root_id

    def add_node(self, node: FairShareNode) -> None:
        """Add or update an organizational node in the fair-share tree.

        Args:
            node: FairShareNode instance to register.

        Raises:
            ValueError: If parent_id is specified but does not exist in the tree.
        """
        if node.parent_id is not None and node.parent_id not in self._nodes:
            msg = f"Parent node '{node.parent_id}' does not exist in fair-share tree"
            raise ValueError(msg)

        self._nodes[node.id] = node
        if node.id not in self._children:
            self._children[node.id] = []

        if node.parent_id is not None:
            if node.parent_id not in self._children:
                self._children[node.parent_id] = []
            if node.id not in self._children[node.parent_id]:
                self._children[node.parent_id].append(node.id)

    def get_node(self, node_id: str) -> FairShareNode | None:
        """Retrieve a registered fair-share node by identifier.

        Args:
            node_id: Unique node identifier.

        Returns:
            FairShareNode if found, None otherwise.
        """
        return self._nodes.get(node_id)

    def record_usage(self, node_id: str, delta_usage: float, timestamp: float) -> None:
        """Record consumed resource units and propagate usage upward to tree root.

        Args:
            node_id: Identifier of the leaf node that consumed resources.
            delta_usage: Incremental compute consumption (slot-seconds, cpu-seconds).
            timestamp: Current evaluation timestamp.

        Raises:
            ValueError: If node_id is not registered or delta_usage is negative.

        Notes/Architectural Intent:
            Usage is propagated up the entire ancestor branch, ensuring departmental
            and team aggregates accurately reflect constituent user activity.
        """
        if node_id not in self._nodes:
            msg = f"Node '{node_id}' not found in fair-share tree"
            raise ValueError(msg)
        if delta_usage < 0.0:
            msg = "delta_usage cannot be negative"
            raise ValueError(msg)

        curr_id: str | None = node_id
        while curr_id is not None:
            node = self._nodes[curr_id]
            node.historical_usage += delta_usage
            node.last_decay_timestamp = max(node.last_decay_timestamp, timestamp)
            curr_id = node.parent_id

    def apply_decay(
        self, timestamp: float, half_life_seconds: float = 604800.0
    ) -> None:
        """Apply exponential half-life decay across all nodes in the hierarchy.

        Args:
            timestamp: Current evaluation timestamp in seconds.
            half_life_seconds: Half-life interval in seconds (defaults to 7 days).

        Raises:
            ValueError: If half_life_seconds <= 0.

        Notes/Architectural Intent:
            Implements continuous decay: U(t) = U(t_0) * exp(-lambda * delta_t),
            where lambda = ln(2) / half_life. Guarantees that historical consumption
            gradually fades, preventing permanent penalization of active users.
        """
        if half_life_seconds <= 0.0:
            msg = "half_life_seconds must be positive"
            raise ValueError(msg)

        decay_rate = math.log(2.0) / half_life_seconds

        for node in self._nodes.values():
            if node.last_decay_timestamp <= 0.0:
                node.last_decay_timestamp = timestamp
                continue

            delta_t = timestamp - node.last_decay_timestamp
            if delta_t > 0.0:
                decay_factor = math.exp(-decay_rate * delta_t)
                node.historical_usage *= decay_factor
                node.last_decay_timestamp = timestamp

    def compute_normalized_shares(self) -> dict[str, float]:
        """Compute the global normalized entitlement fraction for every node in the tree.

        Returns:
            Dictionary mapping node IDs to their normalized fraction in (0.0, 1.0].

        Notes/Architectural Intent:
            Recursively distributes shares down the hierarchy. The root node has
            normalized share 1.0. Children partition their parent's share strictly
            proportional to their relative shares weight.
        """
        normalized: dict[str, float] = {self._root_id: 1.0}
        queue = [self._root_id]

        while queue:
            parent_id = queue.pop(0)
            parent_share = normalized[parent_id]
            children_ids = self._children.get(parent_id, [])
            if not children_ids:
                continue

            total_child_shares = sum(
                self._nodes[child_id].shares for child_id in children_ids
            )
            if total_child_shares <= 0.0:
                continue

            for child_id in children_ids:
                child_node = self._nodes[child_id]
                child_fraction = child_node.shares / total_child_shares
                normalized[child_id] = parent_share * child_fraction
                queue.append(child_id)

        return normalized

    def compute_fairshare_factor(
        self, node_id: str, timestamp: float, half_life_seconds: float = 604800.0
    ) -> float:
        """Calculate the dynamic fair-share scheduling coefficient for an entity.

        Args:
            node_id: Target entity identifier (user or team).
            timestamp: Current scheduling timestamp.
            half_life_seconds: Usage decay half-life in seconds.

        Returns:
            Normalized fair-share factor in range (0.0, 1.0].

        Notes/Architectural Intent:
            Uses the Slurm/LSF fair-tree formulation:
                Factor = 2 ^ (- (effective_usage_fraction / target_share_fraction))
            Entities with zero usage achieve the maximum priority factor of 1.0.
            Entities consuming exactly their target share receive 0.5.
            Heavy consumers' priority converges gracefully toward 0.0 without hard cutoffs.
        """
        if node_id not in self._nodes:
            return 1.0

        self.apply_decay(timestamp, half_life_seconds)

        root_usage = self._nodes[self._root_id].historical_usage
        if root_usage <= 0.0:
            return 1.0

        node_usage = self._nodes[node_id].historical_usage
        if node_usage <= 0.0:
            return 1.0

        normalized_shares = self.compute_normalized_shares()
        target_share = normalized_shares.get(node_id, 0.0)
        if target_share <= 0.0:
            return 0.0

        actual_usage_fraction = node_usage / root_usage
        ratio = actual_usage_fraction / target_share

        return float(math.pow(2.0, -ratio))


__all__ = [
    "FairShareNode",
    "FairShareTree",
]
