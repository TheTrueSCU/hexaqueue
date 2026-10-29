"""Unit tests for instance pool governor port contract."""

from collections.abc import Sequence

import pytest

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.pool import (
    InstancePoolState,
    PoolScaleRequest,
    PoolScaleResult,
)
from hexaqueue_core.ports.pool import InstancePoolGovernorPort


class DummyInstancePoolGovernor(InstancePoolGovernorPort):
    """In-memory dummy implementation of InstancePoolGovernorPort."""

    def __init__(self) -> None:
        """Initialize in-memory dummy governor with test pool."""
        self.pools: dict[str, InstancePoolState] = {
            "test-pool": InstancePoolState(
                pool_id="test-pool",
                provider=CspProvider.LOCAL,
                min_nodes=0,
                max_nodes=5,
                desired_nodes=1,
                current_nodes=1,
            )
        }

    async def get_pool_state(self, pool_id: str) -> InstancePoolState:
        """Query pool state."""
        return self.pools[pool_id]

    async def list_pools(self) -> Sequence[InstancePoolState]:
        """List all pools."""
        return list(self.pools.values())

    async def scale_pool(self, request: PoolScaleRequest) -> PoolScaleResult:
        """Resize pool."""
        prev = self.pools[request.pool_id].current_nodes
        updated = self.pools[request.pool_id].model_copy(
            update={
                "desired_nodes": request.target_nodes,
                "current_nodes": request.target_nodes,
            }
        )
        self.pools[request.pool_id] = updated
        return PoolScaleResult(
            pool_id=request.pool_id,
            previous_nodes=prev,
            target_nodes=request.target_nodes,
            success=True,
            message="Resized successfully",
        )


@pytest.mark.asyncio
async def test_dummy_pool_governor_contract() -> None:
    """Verify governor port lifecycle operations."""
    gov = DummyInstancePoolGovernor()
    pools = await gov.list_pools()
    count = len(pools)
    assert count == 1

    state = await gov.get_pool_state("test-pool")
    p_id = state.pool_id
    assert p_id == "test-pool"

    res = await gov.scale_pool(
        PoolScaleRequest(pool_id="test-pool", target_nodes=3, reason="Test scale")
    )
    ok = res.success
    assert ok is True
    target = res.target_nodes
    assert target == 3

    new_state = await gov.get_pool_state("test-pool")
    curr = new_state.current_nodes
    assert curr == 3
