"""Port interfaces for distributed split/join barrier resolution.

Notes/Architectural Intent:
    Declares the abstract contract for orchestrating partition dispatch across
    remote compute nodes, awaiting barrier synchronization, and aggregating outputs
    for dynamically mapped steps (@wf.map_step) and concurrent split execution paths.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from hexaqueue_workflow.domain.barrier import (
    BarrierPartition,
    BarrierResolutionSummary,
)

__all__ = [
    "SplitJoinBarrierPort",
]


class SplitJoinBarrierPort(ABC):
    """Abstract port for dispatching partitions and awaiting join barrier synchronization."""

    @abstractmethod
    async def dispatch_partition(
        self,
        run_id: str,
        step_name: str,
        partition: BarrierPartition,
        payload: Any,
    ) -> BarrierPartition:
        """Dispatch a single partition to a target compute node.

        Args:
            run_id: Parent workflow execution run identifier.
            step_name: Parent step name fanning out.
            partition: Target partition metadata.
            payload: Input payload or element for the partition.

        Returns:
            Updated BarrierPartition with dispatch confirmation or executed status.
        """

    @abstractmethod
    async def await_barrier(
        self,
        run_id: str,
        step_name: str,
        partitions: list[BarrierPartition],
        timeout_seconds: float | None = None,
    ) -> BarrierResolutionSummary:
        """Wait for all partitions to arrive at the join barrier and return aggregated results.

        Args:
            run_id: Parent workflow execution run identifier.
            step_name: Parent step name undergoing join barrier resolution.
            partitions: List of dispatched partitions to synchronize.
            timeout_seconds: Maximum duration to wait before timing out.

        Returns:
            BarrierResolutionSummary consolidating partition outcomes and ordered outputs.
        """
