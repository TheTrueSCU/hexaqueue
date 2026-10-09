"""Unit tests for in-memory budget accounting and rate model adapters.

Notes/Architectural Intent:
    Tests reservation hold creation, over-budget rejection, segmented preemption
    settlements, zero-leak full releases, and tenant account reconciliation.
"""

import pytest

from hexaqueue_core.adapters.budget.in_memory import (
    InMemoryBudgetAccountingAdapter,
    ZeroCostRateModelAdapter,
)
from hexaqueue_core.domain.exceptions import HexaqueueError, QuotaExceededError
from hexaqueue_core.domain.resources import ResourceRequirements


@pytest.mark.asyncio
async def test_in_memory_budget_accounting_lifecycle() -> None:
    """Verify reservation and settlement cycle."""
    budget = InMemoryBudgetAccountingAdapter(initial_balances={"tenant-1": 100.0})
    hold_id = await budget.reserve_budget(
        tenant_id="tenant-1", job_id="job-1", estimated_credits=20.0
    )
    is_valid_prefix = hold_id.startswith("hold-")
    assert is_valid_prefix is True

    # Overdraft should raise QuotaExceededError
    with pytest.raises(QuotaExceededError):
        await budget.reserve_budget(
            tenant_id="tenant-1", job_id="job-2", estimated_credits=100.0
        )

    # Settle
    await budget.settle_budget(reservation_id=hold_id, actual_credits=15.0)
    # Non-existent settle should not fail
    await budget.settle_budget(reservation_id="unknown-hold", actual_credits=5.0)


@pytest.mark.asyncio
async def test_in_memory_budget_segment_settlement() -> None:
    """Verify incremental segment settlements upon preemption."""
    budget = InMemoryBudgetAccountingAdapter(initial_balances={"tenant-1": 100.0})
    hold_id = await budget.reserve_budget(
        tenant_id="tenant-1", job_id="job-preempt", estimated_credits=50.0
    )

    # Settle segment 1 (e.g. ran for 10 minutes prior to first preemption)
    seg1 = await budget.settle_segment(reservation_id=hold_id, segment_credits=10.0)
    assert seg1 == 10.0

    # Settle segment 2 (e.g. ran for another 15 minutes prior to second preemption)
    seg2 = await budget.settle_segment(reservation_id=hold_id, segment_credits=15.0)
    assert seg2 == 25.0

    # Final completion
    await budget.settle_budget(reservation_id=hold_id, actual_credits=25.0)

    account = await budget.get_account("tenant-1")
    assert account.settled_total == 25.0
    assert account.available_balance == 75.0


@pytest.mark.asyncio
async def test_in_memory_budget_release() -> None:
    """Verify releasing budget hold returns 100% of held credits."""
    budget = InMemoryBudgetAccountingAdapter(initial_balances={"tenant-1": 50.0})
    hold_id = await budget.reserve_budget(
        tenant_id="tenant-1", job_id="job-cancel", estimated_credits=30.0
    )

    account_held = await budget.get_account("tenant-1")
    assert account_held.available_balance == 20.0

    await budget.release_budget(hold_id)

    account_released = await budget.get_account("tenant-1")
    assert account_released.available_balance == 50.0
    assert account_released.settled_total == 0.0

    # Double release raises HexaqueueError
    with pytest.raises(HexaqueueError):
        await budget.release_budget(hold_id)


def test_zero_cost_rate_model() -> None:
    """Verify rate model returns 0.0 credits."""
    model = ZeroCostRateModelAdapter()
    cost = model.calculate_estimated_cost(ResourceRequirements())
    assert cost == 0.0


__all__ = [
    "test_in_memory_budget_accounting_lifecycle",
    "test_in_memory_budget_release",
    "test_in_memory_budget_segment_settlement",
    "test_zero_cost_rate_model",
]
