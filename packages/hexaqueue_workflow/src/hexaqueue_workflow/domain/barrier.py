"""Domain models for distributed split/join barriers across compute nodes.

Notes/Architectural Intent:
    Represents discrete partitions, node assignments, and synchronization summaries
    for dynamic mapped steps (@wf.map_step) and concurrent split branches.
    Provides deterministic tracking of distributed worker execution frontiers.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "BarrierPartition",
    "BarrierResolutionSummary",
    "BarrierState",
]


class BarrierState(StrEnum):
    """Lifecycle synchronization states of a distributed split/join barrier."""

    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    SYNCHRONIZING = "SYNCHRONIZING"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"


class BarrierPartition(BaseModel):
    """Value object capturing a single partition dispatched to a compute node.

    Notes/Architectural Intent:
        Encapsulates partition index, assigned compute node address/identifier,
        individual partition execution status, and staged output/error payload.
    """

    model_config = ConfigDict(frozen=True)

    partition_id: int = Field(description="Zero-indexed partition sequence number.")
    sub_step_name: str = Field(
        description="Unique qualified sub-step name (e.g. 'process[0]')."
    )
    node_id: str = Field(
        default="localhost",
        description="Target compute node or gRPC worker identifier.",
    )
    status: str = Field(
        default="PENDING", description="Current execution state of the partition."
    )
    payload: Any = Field(
        default=None, description="Partition input arguments or output payload."
    )
    error: str | None = Field(
        default=None, description="Error message if partition failed."
    )


class BarrierResolutionSummary(BaseModel):
    """Aggregate outcome of a split/join barrier after all partitions synchronize.

    Notes/Architectural Intent:
        Aggregates outputs from parallel compute nodes, tracking partition success
        ratios, total duration, and barrier state for downstream step consumption.
    """

    model_config = ConfigDict(frozen=True)

    step_name: str = Field(
        description="Name of the fanned-out or dynamically mapped parent step."
    )
    total_partitions: int = Field(
        description="Total number of partitions created at split."
    )
    completed_partitions: int = Field(
        description="Number of partitions successfully evaluated."
    )
    failed_partitions: int = Field(
        description="Number of partitions that encountered terminal errors."
    )
    state: BarrierState = Field(
        description="Terminal or active synchronization state of the barrier."
    )
    outputs: list[Any] = Field(
        default_factory=list,
        description="Ordered collection of partition output payloads.",
    )
    duration_seconds: float = Field(
        default=0.0, description="Elapsed barrier resolution duration in seconds."
    )
