import pytest
from pydantic import ValidationError

from hexaqueue_workflow.domain.barrier import (
    BarrierPartition,
    BarrierResolutionSummary,
    BarrierState,
)


def test_barrier_state_enum() -> None:
    """Verify all BarrierState members and string representations."""
    assert BarrierState.PENDING == "PENDING"
    assert BarrierState.DISPATCHED == "DISPATCHED"
    assert BarrierState.SYNCHRONIZING == "SYNCHRONIZING"
    assert BarrierState.RESOLVED == "RESOLVED"
    assert BarrierState.FAILED == "FAILED"


def test_barrier_partition_defaults_and_immutability() -> None:
    """Verify BarrierPartition initializes correctly and is frozen."""
    partition = BarrierPartition(
        partition_id=0,
        sub_step_name="step[0]",
        node_id="node-1",
        payload={"input": 42},
    )

    assert partition.partition_id == 0
    assert partition.sub_step_name == "step[0]"
    assert partition.node_id == "node-1"
    assert partition.status == "PENDING"
    assert partition.payload == {"input": 42}
    assert partition.error is None

    attr = "status"
    with pytest.raises(ValidationError):
        setattr(partition, attr, "RUNNING")


def test_barrier_resolution_summary_model() -> None:
    """Verify BarrierResolutionSummary aggregates partitions and is frozen."""
    summary = BarrierResolutionSummary(
        step_name="map_task",
        total_partitions=3,
        completed_partitions=3,
        failed_partitions=0,
        state=BarrierState.RESOLVED,
        outputs=[1, 2, 3],
        duration_seconds=0.45,
    )

    assert summary.step_name == "map_task"
    assert summary.total_partitions == 3
    assert summary.completed_partitions == 3
    assert summary.failed_partitions == 0
    assert summary.state == BarrierState.RESOLVED
    assert summary.outputs == [1, 2, 3]
    assert summary.duration_seconds == 0.45

    field = "state"
    with pytest.raises(ValidationError):
        setattr(summary, field, BarrierState.FAILED)
