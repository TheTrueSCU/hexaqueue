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


@pytest.mark.asyncio
async def test_reconcile_pool_circuit_breaker_on_stall_and_capacity_error() -> None:
    """Verify autoscaler trips circuit breaker on stalled scale-up or CSP capacity error."""
    pool = InstancePoolState(
        pool_id="pool-a1",
        provider=CspProvider.OCI,
        min_nodes=0,
        max_nodes=4,
        desired_nodes=2,
        current_nodes=2,
        ready_nodes=0,
    )
    gov = MockGovernor(pool)
    autoscaler = BudgetAwareInstancePoolAutoscaler(
        governors={"pool-a1": gov},
        scale_up_grace_seconds=60.0,
        circuit_cooldown_seconds=120.0,
    )

    # First tick at t=1000 starts grace timer
    dec1 = await autoscaler.reconcile_pool(
        pool_id="pool-a1", pending_jobs=2, running_jobs=0, now=1000.0
    )
    assert dec1.action in ("SCALE_UP", "NOOP")
    status1 = autoscaler.get_pool_circuit_status("pool-a1", now=1000.0)
    assert status1["state"] == "CLOSED"

    # Simulate pool still having 0 ready_nodes at t=1070 (> 60s grace) -> trips circuit and scales to 0
    gov.pool = gov.pool.model_copy(update={"desired_nodes": 2, "ready_nodes": 0})
    dec2 = await autoscaler.reconcile_pool(
        pool_id="pool-a1", pending_jobs=2, running_jobs=0, now=1070.0
    )
    assert dec2.action == "SCALE_DOWN"
    assert dec2.target_nodes == 0
    status2 = autoscaler.get_pool_circuit_status("pool-a1", now=1070.0)
    assert status2["state"] == "OPEN"
    assert status2["trip_count"] == 1

    # While OPEN, subsequent scale-up request is NOOP
    dec3 = await autoscaler.reconcile_pool(
        pool_id="pool-a1", pending_jobs=5, running_jobs=0, now=1080.0
    )
    assert dec3.action == "NOOP"
    assert "Circuit breaker OPEN" in dec3.reason

    # Reset when ready_nodes > 0
    gov.pool = gov.pool.model_copy(
        update={"desired_nodes": 1, "current_nodes": 1, "ready_nodes": 1}
    )
    _dec4 = await autoscaler.reconcile_pool(
        pool_id="pool-a1", pending_jobs=0, running_jobs=1, now=1200.0
    )
    status4 = autoscaler.get_pool_circuit_status("pool-a1", now=1200.0)
    assert status4["state"] == "CLOSED"
