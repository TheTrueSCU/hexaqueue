"""Unit tests for BudgetAwareInstancePoolAutoscaler."""

from unittest.mock import AsyncMock

import pytest

from hexaqueue_core.domain.budget import TenantAccount
from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.pool import (
    InstancePoolState,
    PoolScaleRequest,
    PoolScaleResult,
)
from hexaqueue_core.ports.budget import BudgetAccountingPort
from hexaqueue_core.ports.pool import InstancePoolGovernorPort
from hexaqueue_server.domain.autoscaler import BudgetAwareInstancePoolAutoscaler


class MockGovernor(InstancePoolGovernorPort):
    """Mock governor for testing autoscaler."""

    def __init__(self, pool: InstancePoolState) -> None:
        """Initialize with state."""
        self.pool = pool
        self.scaled_requests: list[PoolScaleRequest] = []

    async def get_pool_state(self, pool_id: str) -> InstancePoolState:
        """Return current state."""
        return self.pool

    async def list_pools(self) -> list[InstancePoolState]:
        """Return list of pools."""
        return [self.pool]

    async def scale_pool(self, request: PoolScaleRequest) -> PoolScaleResult:
        """Record scale request and update current nodes."""
        self.scaled_requests.append(request)
        self.pool = self.pool.model_copy(
            update={
                "desired_nodes": request.target_nodes,
                "current_nodes": request.target_nodes,
            }
        )
        return PoolScaleResult(
            pool_id=request.pool_id,
            previous_nodes=0,
            target_nodes=request.target_nodes,
            success=True,
            message="OK",
        )


def test_evaluate_scaling_scale_up() -> None:
    """Verify scale-up decision when queue backlog exists."""
    pool = InstancePoolState(
        pool_id="pool-1",
        provider=CspProvider.AWS,
        min_nodes=0,
        max_nodes=10,
        current_nodes=0,
    )
    autoscaler = BudgetAwareInstancePoolAutoscaler()
    decision = autoscaler.evaluate_scaling(pool, pending_jobs=3, running_jobs=0)
    action = decision.action
    assert action == "SCALE_UP"
    target = decision.target_nodes
    assert target == 3


def test_evaluate_scaling_max_nodes_clamp() -> None:
    """Verify autoscaler clamps scale-up to max_nodes."""
    pool = InstancePoolState(
        pool_id="pool-1",
        provider=CspProvider.AWS,
        min_nodes=0,
        max_nodes=5,
        current_nodes=5,
    )
    autoscaler = BudgetAwareInstancePoolAutoscaler()
    decision = autoscaler.evaluate_scaling(pool, pending_jobs=20, running_jobs=5)
    action = decision.action
    assert action == "NOOP"
    target = decision.target_nodes
    assert target == 5


def test_evaluate_scaling_throttled_by_budget() -> None:
    """Verify autoscaler throttles scale-up if budget reserve is insufficient."""
    pool = InstancePoolState(
        pool_id="pool-1",
        provider=CspProvider.AWS,
        min_nodes=0,
        max_nodes=10,
        current_nodes=0,
    )
    autoscaler = BudgetAwareInstancePoolAutoscaler(min_budget_reserve=5.0)
    decision = autoscaler.evaluate_scaling(
        pool, pending_jobs=4, running_jobs=0, available_budget=2.5
    )
    action = decision.action
    assert action == "THROTTLED_BUDGET"
    target = decision.target_nodes
    assert target == 0


def test_evaluate_scaling_scale_down_to_zero() -> None:
    """Verify autoscaler scales down to floor when queue is empty and idle."""
    pool = InstancePoolState(
        pool_id="pool-1",
        provider=CspProvider.AWS,
        min_nodes=0,
        max_nodes=10,
        current_nodes=4,
    )
    autoscaler = BudgetAwareInstancePoolAutoscaler()
    decision = autoscaler.evaluate_scaling(pool, pending_jobs=0, running_jobs=0)
    action = decision.action
    assert action == "SCALE_DOWN"
    target = decision.target_nodes
    assert target == 0


def test_evaluate_scaling_idle_noop() -> None:
    """Verify autoscaler is NOOP when idle at scaling floor."""
    pool = InstancePoolState(
        pool_id="pool-1",
        provider=CspProvider.AWS,
        min_nodes=0,
        max_nodes=10,
        current_nodes=0,
    )
    autoscaler = BudgetAwareInstancePoolAutoscaler()
    decision = autoscaler.evaluate_scaling(pool, pending_jobs=0, running_jobs=0)
    action = decision.action
    assert action == "NOOP"


@pytest.mark.asyncio
async def test_reconcile_pool_success() -> None:
    """Verify reconcile_pool invokes governor scale_pool."""
    pool = InstancePoolState(
        pool_id="pool-1",
        provider=CspProvider.AWS,
        min_nodes=0,
        max_nodes=10,
        current_nodes=0,
    )
    gov = MockGovernor(pool)
    budget = AsyncMock(spec=BudgetAccountingPort)
    budget.get_account.return_value = TenantAccount(
        tenant_id="tenant-1",
        credit_balance=100.0,
        settled_total=0.0,
        active_holds_total=0.0,
    )

    autoscaler = BudgetAwareInstancePoolAutoscaler(
        governors={"pool-1": gov},
        budget_port=budget,
    )

    decision = await autoscaler.reconcile_pool(
        pool_id="pool-1",
        pending_jobs=2,
        running_jobs=0,
        tenant_id="tenant-1",
    )
    action = decision.action
    assert action == "SCALE_UP"
    scaled_count = len(gov.scaled_requests)
    assert scaled_count == 1
    assert gov.scaled_requests[0].target_nodes == 2


@pytest.mark.asyncio
async def test_reconcile_pool_unregistered() -> None:
    """Verify error when reconciling unknown pool."""
    autoscaler = BudgetAwareInstancePoolAutoscaler()
    with pytest.raises(HexaqueueError, match="No governor registered"):
        await autoscaler.reconcile_pool("unknown-pool", pending_jobs=1)
