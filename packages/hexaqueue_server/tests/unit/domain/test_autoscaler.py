"""Unit tests for BudgetAwareInstancePoolAutoscaler."""

from datetime import UTC, datetime, timedelta
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
from hexaqueue_server.domain.autoscaler import (
    BudgetAwareInstancePoolAutoscaler,
    BudgetStrategyMode,
    CreditPacingPolicy,
)


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
    dec4 = await autoscaler.reconcile_pool(
        pool_id="pool-a1", pending_jobs=0, running_jobs=1, now=1200.0
    )
    dec4_action = dec4.action
    assert dec4_action == "NOOP"
    status4 = autoscaler.get_pool_circuit_status("pool-a1", now=1200.0)
    assert status4["state"] == "CLOSED"


def test_credit_pacing_policy_metering_and_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify CreditPacingPolicy meters daily allowance and throttles after expiry."""
    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    start = datetime(2026, 11, 2, 4, 20, tzinfo=UTC)
    expiry = datetime(2026, 12, 2, 4, 20, tzinfo=UTC)

    policy = CreditPacingPolicy(
        total_credits_usd=300.0,
        spent_credits_usd=1.53,
        reserve_credits_usd=15.0,
        hourly_cost_per_node_usd=0.046,
        start_time=start,
        expiry_time=expiry,
    )
    assert policy.is_expired(now) is False
    assert policy.spendable_remaining_usd() == pytest.approx(283.47, abs=0.01)
    assert policy.daily_allowance_usd(now) > 20.0
    assert policy.recommended_max_nodes(hard_ceiling=6, now=now) == 6

    # After expiry -> allowance is 0 and autoscaler throttles / scales down to 0
    after_expiry = expiry + timedelta(minutes=1)
    assert policy.is_expired(after_expiry) is True
    assert policy.recommended_max_nodes(hard_ceiling=6, now=after_expiry) == 0

    expired_policy = policy.model_copy(
        update={"expiry_time": datetime.now(UTC) - timedelta(seconds=60)}
    )
    pool = InstancePoolState(
        pool_id="pool-a4",
        provider=CspProvider.OCI,
        min_nodes=0,
        max_nodes=6,
        current_nodes=0,
    )
    autoscaler = BudgetAwareInstancePoolAutoscaler(credit_pacing=expired_policy)
    dec_throttled = autoscaler.evaluate_scaling(pool, pending_jobs=4)
    assert dec_throttled.action == "THROTTLED_BUDGET"
    assert dec_throttled.target_nodes == 0

    active_pool = pool.model_copy(update={"current_nodes": 2})
    dec_down = autoscaler.evaluate_scaling(active_pool, pending_jobs=4)
    assert dec_down.action == "SCALE_DOWN"
    assert dec_down.target_nodes == 0

    monkeypatch.setenv("HEXAQUEUE_CREDIT_EXPIRY_DATE", "2026-12-02T04:20:19Z")
    monkeypatch.setenv("HEXAQUEUE_CREDIT_START_DATE", "2026-11-02T04:20:19Z")
    monkeypatch.setenv("HEXAQUEUE_CREDIT_TOTAL_USD", "300.0")
    monkeypatch.setenv("HEXAQUEUE_CREDIT_SPENT_USD", "1.53")
    monkeypatch.setenv("HEXAQUEUE_CREDIT_RESERVE_USD", "15.0")
    env_policy = CreditPacingPolicy.from_env()
    assert env_policy is not None
    total_credits = env_policy.total_credits_usd
    assert total_credits == 300.0


def test_budget_strategy_modes_and_env_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify all five BudgetStrategyMode policies and environment parsing rules."""
    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    expiry = datetime(2026, 12, 2, 4, 20, tzinfo=UTC)

    # 1. FREE_TIER_ONLY locks burst pool to 0 regardless of remaining credits
    free_tier = CreditPacingPolicy(
        strategy=BudgetStrategyMode.FREE_TIER_ONLY,
        total_credits_usd=300.0,
        spent_credits_usd=0.0,
        expiry_time=expiry,
    )
    free_allowance = free_tier.daily_allowance_usd(now)
    free_nodes = free_tier.recommended_max_nodes(hard_ceiling=6, now=now)
    assert free_allowance == 0.0
    assert free_nodes == 0

    # 2. LINEAR_CREDIT_PACING without expiry falls back to daily_cap_usd & spendable balance
    linear_no_expiry = CreditPacingPolicy(
        strategy=BudgetStrategyMode.LINEAR_CREDIT_PACING,
        total_credits_usd=300.0,
        spent_credits_usd=10.0,
        reserve_credits_usd=15.0,
        daily_cap_usd=1.0,
        hourly_cost_per_node_usd=0.05,
        expiry_time=None,
    )
    no_exp_flag = linear_no_expiry.is_expired(now)
    no_exp_allowance = linear_no_expiry.daily_allowance_usd(now)
    no_exp_nodes = linear_no_expiry.recommended_max_nodes(
        hard_ceiling=10, assumed_active_hours_per_day=4.0, now=now
    )
    assert no_exp_flag is False
    assert no_exp_allowance == 1.0
    assert no_exp_nodes == 5

    # 3. FRONT_LOADED_CREDITS bursts to hard_ceiling while credits and window hold
    front_loaded = CreditPacingPolicy(
        strategy=BudgetStrategyMode.FRONT_LOADED_CREDITS,
        total_credits_usd=300.0,
        spent_credits_usd=100.0,
        reserve_credits_usd=15.0,
        expiry_time=expiry,
    )
    front_allowance = front_loaded.daily_allowance_usd(now)
    front_nodes = front_loaded.recommended_max_nodes(hard_ceiling=8, now=now)
    assert front_allowance == 185.0
    assert front_nodes == 8

    # Exhausted reserve or past expiry blocks FRONT_LOADED_CREDITS
    depleted_front = front_loaded.model_copy(update={"spent_credits_usd": 290.0})
    depleted_nodes = depleted_front.recommended_max_nodes(hard_ceiling=8, now=now)
    assert depleted_nodes == 0
    expired_front_nodes = front_loaded.recommended_max_nodes(
        hard_ceiling=8, now=expiry + timedelta(seconds=1)
    )
    assert expired_front_nodes == 0

    # 4. FIXED_DAILY_CAP enforces daily_cap_usd even if promotional expiry passed
    fixed_cap = CreditPacingPolicy(
        strategy=BudgetStrategyMode.FIXED_DAILY_CAP,
        daily_cap_usd=0.40,
        hourly_cost_per_node_usd=0.05,
        expiry_time=now - timedelta(days=5),
    )
    fixed_allowance = fixed_cap.daily_allowance_usd(now)
    fixed_nodes = fixed_cap.recommended_max_nodes(
        hard_ceiling=10, assumed_active_hours_per_day=4.0, now=now
    )
    assert fixed_allowance == 0.40
    assert fixed_nodes == 2

    # 5. UNCONSTRAINED allows hard_ceiling
    unconstrained = CreditPacingPolicy(
        strategy=BudgetStrategyMode.UNCONSTRAINED,
        total_credits_usd=50.0,
        daily_cap_usd=25.0,
    )
    uncon_allowance = unconstrained.daily_allowance_usd(now)
    uncon_nodes = unconstrained.recommended_max_nodes(hard_ceiling=7, now=now)
    assert uncon_allowance == 50.0
    assert uncon_nodes == 7

    # Env parsing: unset vars -> None
    for var in (
        "HEXAQUEUE_BUDGET_STRATEGY",
        "HEXAQUEUE_CREDIT_EXPIRY_DATE",
        "HEXAQUEUE_CREDIT_START_DATE",
        "HEXAQUEUE_DAILY_CAP_USD",
    ):
        monkeypatch.delenv(var, raising=False)
    empty_env = CreditPacingPolicy.from_env()
    assert empty_env is None

    # Env parsing: HEXAQUEUE_DAILY_CAP_USD alone -> FIXED_DAILY_CAP
    monkeypatch.setenv("HEXAQUEUE_DAILY_CAP_USD", "12.5")
    cap_env = CreditPacingPolicy.from_env()
    assert cap_env is not None
    cap_strategy = cap_env.strategy
    cap_val = cap_env.daily_cap_usd
    assert cap_strategy == BudgetStrategyMode.FIXED_DAILY_CAP
    assert cap_val == 12.5

    # Env parsing: explicit HEXAQUEUE_BUDGET_STRATEGY and invalid value check
    monkeypatch.setenv("HEXAQUEUE_BUDGET_STRATEGY", "front_loaded_credits")
    strategy_env = CreditPacingPolicy.from_env()
    assert strategy_env is not None
    parsed_strategy = strategy_env.strategy
    assert parsed_strategy == BudgetStrategyMode.FRONT_LOADED_CREDITS

    monkeypatch.setenv("HEXAQUEUE_BUDGET_STRATEGY", "UNKNOWN_MODE")
    with pytest.raises(ValueError, match="UNKNOWN_MODE"):
        CreditPacingPolicy.from_env()


def test_autoscaler_runtime_strategy_switching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify BudgetAwareInstancePoolAutoscaler supports live policy swaps."""
    for var in (
        "HEXAQUEUE_BUDGET_STRATEGY",
        "HEXAQUEUE_CREDIT_EXPIRY_DATE",
        "HEXAQUEUE_DAILY_CAP_USD",
    ):
        monkeypatch.delenv(var, raising=False)

    pool = InstancePoolState(
        pool_id="pool-a4",
        provider=CspProvider.OCI,
        min_nodes=0,
        max_nodes=6,
        current_nodes=2,
    )
    future_expiry = datetime.now(UTC) + timedelta(days=10)
    linear = CreditPacingPolicy(
        strategy=BudgetStrategyMode.LINEAR_CREDIT_PACING,
        total_credits_usd=300.0,
        spent_credits_usd=0.0,
        reserve_credits_usd=15.0,
        expiry_time=future_expiry,
    )
    autoscaler = BudgetAwareInstancePoolAutoscaler(credit_pacing=linear)
    initial_policy = autoscaler.credit_pacing
    assert initial_policy is not None
    initial_mode = initial_policy.strategy
    assert initial_mode == BudgetStrategyMode.LINEAR_CREDIT_PACING

    dec_linear = autoscaler.evaluate_scaling(pool, pending_jobs=3)
    action_linear = dec_linear.action
    target_linear = dec_linear.target_nodes
    assert action_linear == "SCALE_UP"
    assert target_linear == 5

    # Switch to FREE_TIER_ONLY at runtime -> active nodes immediately scale to 0
    autoscaler.set_credit_pacing(
        CreditPacingPolicy(strategy=BudgetStrategyMode.FREE_TIER_ONLY)
    )
    free_policy = autoscaler.credit_pacing
    assert free_policy is not None
    assert free_policy.strategy == BudgetStrategyMode.FREE_TIER_ONLY
    dec_free = autoscaler.evaluate_scaling(pool, pending_jobs=3)
    action_free = dec_free.action
    target_free = dec_free.target_nodes
    reason_free = dec_free.reason
    assert action_free == "SCALE_DOWN"
    assert target_free == 0
    assert "FREE_TIER_ONLY" in reason_free

    idle_pool = pool.model_copy(update={"current_nodes": 0})
    dec_free_idle = autoscaler.evaluate_scaling(idle_pool, pending_jobs=3)
    assert dec_free_idle.action == "THROTTLED_BUDGET"
    assert "FREE_TIER_ONLY" in dec_free_idle.reason

    # Switch to UNCONSTRAINED -> full pool scale-up allowed again
    autoscaler.set_credit_pacing(
        CreditPacingPolicy(strategy=BudgetStrategyMode.UNCONSTRAINED)
    )
    dec_uncon = autoscaler.evaluate_scaling(idle_pool, pending_jobs=6)
    action_uncon = dec_uncon.action
    target_uncon = dec_uncon.target_nodes
    assert action_uncon == "SCALE_UP"
    assert target_uncon == 6

    # Clear policy entirely (None)
    autoscaler.set_credit_pacing(None)
    cleared_policy = autoscaler.credit_pacing
    assert cleared_policy is None
    dec_none = autoscaler.evaluate_scaling(idle_pool, pending_jobs=4)
    assert dec_none.action == "SCALE_UP"
    assert dec_none.target_nodes == 4
