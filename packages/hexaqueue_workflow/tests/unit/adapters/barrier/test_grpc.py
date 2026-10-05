"""Unit tests for GrpcSplitJoinBarrierAdapter."""

import asyncio
from typing import Any

import pytest

from hexaqueue_workflow.adapters.barrier.grpc import GrpcSplitJoinBarrierAdapter
from hexaqueue_workflow.domain.barrier import (
    BarrierPartition,
    BarrierState,
)


@pytest.mark.asyncio
async def test_grpc_barrier_dispatch_and_await_default() -> None:
    """Verify default dispatch and join barrier synchronization."""
    adapter = GrpcSplitJoinBarrierAdapter(node_endpoints={"node-0": "localhost:50051"})

    p1 = BarrierPartition(partition_id=0, sub_step_name="step[0]", node_id="node-0")
    p2 = BarrierPartition(partition_id=1, sub_step_name="step[1]", node_id="node-0")

    d1 = await adapter.dispatch_partition("run-1", "step", p1, 10)
    d2 = await adapter.dispatch_partition("run-1", "step", p2, 20)

    assert d1.status == "COMPLETED"
    assert d2.status == "COMPLETED"

    summary = await adapter.await_barrier("run-1", "step", [d2, d1])
    assert summary.step_name == "step"
    assert summary.total_partitions == 2
    assert summary.completed_partitions == 2
    assert summary.failed_partitions == 0
    assert summary.state == BarrierState.RESOLVED
    assert summary.outputs == [10, 20]
    assert summary.duration_seconds >= 0.0


@pytest.mark.asyncio
async def test_grpc_barrier_custom_remote_executor() -> None:
    """Verify custom remote executor callable is invoked during dispatch."""

    async def _mock_rpc(
        run_id: str, step_name: str, part: BarrierPartition, payload: Any
    ) -> Any:
        return payload * 2

    adapter = GrpcSplitJoinBarrierAdapter(remote_executor=_mock_rpc)
    p = BarrierPartition(partition_id=0, sub_step_name="map[0]", node_id="worker-1")

    d = await adapter.dispatch_partition("run-2", "map", p, 21)
    assert d.status == "COMPLETED"
    assert d.payload == 42

    summary = await adapter.await_barrier("run-2", "map", [d])
    assert summary.state == BarrierState.RESOLVED
    assert summary.outputs == [42]


@pytest.mark.asyncio
async def test_grpc_barrier_remote_executor_failure() -> None:
    """Verify failed partition is captured and results in FAILED barrier state."""

    def _failing_rpc(
        run_id: str, step_name: str, part: BarrierPartition, payload: Any
    ) -> Any:
        msg = "RPC Connection Refused"
        raise ConnectionError(msg)

    adapter = GrpcSplitJoinBarrierAdapter(remote_executor=_failing_rpc)
    p = BarrierPartition(
        partition_id=0, sub_step_name="failing[0]", node_id="worker-fail"
    )

    d = await adapter.dispatch_partition("run-3", "failing", p, 100)
    assert d.status == "FAILED"
    assert "RPC Connection Refused" in (d.error or "")

    summary = await adapter.await_barrier("run-3", "failing", [d])
    assert summary.failed_partitions == 1
    assert summary.state == BarrierState.FAILED
    assert summary.outputs == [None]


@pytest.mark.asyncio
async def test_grpc_barrier_timeout() -> None:
    """Verify timeout when synchronization takes longer than allowed."""
    from unittest.mock import patch

    adapter = GrpcSplitJoinBarrierAdapter()
    p = BarrierPartition(partition_id=0, sub_step_name="slow[0]", node_id="worker-slow")

    # 1. timeout_seconds=1.0 calls wait_for
    with patch("asyncio.wait_for", wraps=asyncio.wait_for) as mock_wait:
        summary = await adapter.await_barrier("run-4", "slow", [p], timeout_seconds=1.0)
        assert summary.state == BarrierState.RESOLVED
        assert mock_wait.called is True
        assert mock_wait.call_args.kwargs.get("timeout") == 1.0

    # 2. timeout_seconds=0 does not call wait_for
    with patch("asyncio.wait_for", wraps=asyncio.wait_for) as mock_wait_zero:
        summary_zero = await adapter.await_barrier(
            "run-4", "slow", [p], timeout_seconds=0
        )
        assert summary_zero.state == BarrierState.RESOLVED
        assert mock_wait_zero.called is False

    # 3. timeout_seconds=-1 does not call wait_for
    with patch("asyncio.wait_for", wraps=asyncio.wait_for) as mock_wait_neg:
        summary_neg = await adapter.await_barrier(
            "run-4", "slow", [p], timeout_seconds=-1
        )
        assert summary_neg.state == BarrierState.RESOLVED
        assert mock_wait_neg.called is False


@pytest.mark.asyncio
async def test_grpc_barrier_node_endpoints_and_error_variations() -> None:
    """Verify node_endpoints default dict and partition error/status branches."""
    # 1. node_endpoints=None -> defaults to {}
    adapter = GrpcSplitJoinBarrierAdapter(node_endpoints=None)
    assert adapter._node_endpoints == {}

    # 2. Partitions in partition_results with status="FAILED" and error=None
    p_fail_no_err = BarrierPartition(
        partition_id=0, sub_step_name="f0", node_id="n0", status="FAILED", error=None
    )
    adapter._partition_results[("r1", "s1", 0)] = "result-0"

    # 3. Partitions with status != "FAILED" but error="something"
    p_err_not_fail = BarrierPartition(
        partition_id=1,
        sub_step_name="f1",
        node_id="n0",
        status="COMPLETED",
        error="boom",
    )
    adapter._partition_results[("r1", "s1", 1)] = "result-1"

    # 4. Partition not in partition_results, payload is None
    p_none = BarrierPartition(
        partition_id=2,
        sub_step_name="f2",
        node_id="n0",
        status="COMPLETED",
        payload=None,
    )

    sum1 = await adapter.await_barrier(
        "r1", "s1", [p_fail_no_err, p_err_not_fail, p_none]
    )
    assert sum1.failed_partitions == 2
    assert sum1.completed_partitions == 1
    assert sum1.outputs == [None, None, None]
