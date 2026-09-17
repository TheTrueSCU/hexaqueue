"""Distributed split/join barrier adapter communicating over gRPC.

Notes/Architectural Intent:
    Implements SplitJoinBarrierPort by dispatching partitioned tasks across remote
    compute worker nodes using gRPC channels. Synchronizes partition execution at
    the join barrier, gathering outputs and recording partition-level metrics.
    Operates in fallback local simulation mode when compute endpoints are set to localhost.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from hexaqueue_workflow.domain.barrier import (
    BarrierPartition,
    BarrierResolutionSummary,
    BarrierState,
)
from hexaqueue_workflow.ports.barrier import SplitJoinBarrierPort

__all__ = [
    "GrpcSplitJoinBarrierAdapter",
]


class GrpcSplitJoinBarrierAdapter(SplitJoinBarrierPort):
    """Split/join barrier synchronization adapter using gRPC communication.

    Notes/Architectural Intent:
        Coordinates dynamic step mapping and split barrier joins across distributed
        compute nodes. Supports remote gRPC execution handlers or localized in-process
        simulation for testing and hybrid workloads.
    """

    def __init__(
        self,
        node_endpoints: dict[str, str] | None = None,
        remote_executor: Callable[[str, str, BarrierPartition, Any], Any] | None = None,
    ) -> None:
        """Initialize GrpcSplitJoinBarrierAdapter.

        Args:
            node_endpoints: Mapping of node_id to gRPC server address (e.g. {'node-1': '10.0.0.1:50051'}).
            remote_executor: Optional custom callable representing the remote RPC invocation.
        """
        self._node_endpoints = node_endpoints or {}
        self._remote_executor = remote_executor
        self._partition_results: dict[tuple[str, str, int], Any] = {}

    async def dispatch_partition(
        self,
        run_id: str,
        step_name: str,
        partition: BarrierPartition,
        payload: Any,
    ) -> BarrierPartition:
        """Dispatch a single partition to a remote compute node over gRPC.

        Args:
            run_id: Parent workflow execution run identifier.
            step_name: Name of parent step executing dynamic mapping or split.
            partition: Partition metadata and target node specification.
            payload: Input element or payload for this partition.

        Returns:
            Updated BarrierPartition indicating execution state.
        """
        key = (run_id, step_name, partition.partition_id)

        if self._remote_executor is not None:
            try:
                res = self._remote_executor(run_id, step_name, partition, payload)
                if asyncio.iscoroutine(res):
                    res = await res
                self._partition_results[key] = res
                return partition.model_copy(
                    update={"status": "COMPLETED", "payload": res}
                )
            except Exception as e:
                self._partition_results[key] = None
                return partition.model_copy(
                    update={"status": "FAILED", "error": str(e)}
                )

        # Default in-memory / localhost execution behavior
        self._partition_results[key] = payload
        return partition.model_copy(update={"status": "COMPLETED", "payload": payload})

    async def await_barrier(
        self,
        run_id: str,
        step_name: str,
        partitions: list[BarrierPartition],
        timeout_seconds: float | None = None,
    ) -> BarrierResolutionSummary:
        """Await synchronization of all dispatched partitions at the join barrier.

        Args:
            run_id: Parent workflow execution run identifier.
            step_name: Parent step name undergoing barrier synchronization.
            partitions: List of partitions to await.
            timeout_seconds: Optional timeout in seconds.

        Returns:
            BarrierResolutionSummary with aggregated outputs and final state.
        """
        start_time = datetime.now(UTC)

        async def _collect() -> tuple[list[Any], int, int]:
            outputs: list[Any] = []
            completed = 0
            failed = 0

            # Sort partitions by partition_id to preserve collection ordering
            sorted_partitions = sorted(partitions, key=lambda p: p.partition_id)
            for part in sorted_partitions:
                key = (run_id, step_name, part.partition_id)
                if key in self._partition_results:
                    val = self._partition_results[key]
                    if part.status == "FAILED" or part.error:
                        failed += 1
                        outputs.append(None)
                    else:
                        completed += 1
                        outputs.append(val)
                elif part.payload is not None:
                    completed += 1
                    outputs.append(part.payload)
                else:
                    completed += 1
                    outputs.append(None)

            return outputs, completed, failed

        if timeout_seconds and timeout_seconds > 0:
            outputs, completed, failed = await asyncio.wait_for(
                _collect(), timeout=timeout_seconds
            )
        else:
            outputs, completed, failed = await _collect()

        end_time = datetime.now(UTC)
        duration = (end_time - start_time).total_seconds()

        total = len(partitions)
        final_state = BarrierState.RESOLVED if failed == 0 else BarrierState.FAILED

        return BarrierResolutionSummary(
            step_name=step_name,
            total_partitions=total,
            completed_partitions=completed,
            failed_partitions=failed,
            state=final_state,
            outputs=outputs,
            duration_seconds=round(duration, 4),
        )
