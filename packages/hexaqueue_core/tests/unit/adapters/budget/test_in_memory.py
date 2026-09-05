"""Unit tests for in-memory budget accounting and rate model adapters."""

import pytest

from hexaqueue_core.adapters.budget.in_memory import (
    InMemoryBudgetAccountingAdapter,
    ZeroCostRateModelAdapter,
)
from hexaqueue_core.domain.exceptions import QuotaExceededError
from hexaqueue_core.domain.resources import ResourceRequirements


@pytest.mark.asyncio
async def test_in_memory_budget_accounting_lifecycle():
    """Verify reservation and settlement cycle."""
    budget = InMemoryBudgetAccountingAdapter(initial_balances={"tenant-1": 100.0})
    hold_id = await budget.reserve_budget(
        tenant_id="tenant-1", job_id="job-1", estimated_credits=20.0
    )
    assert hold_id.startswith("hold-")

    # Overdraft should raise QuotaExceededError
    with pytest.raises(QuotaExceededError):
        await budget.reserve_budget(
            tenant_id="tenant-1", job_id="job-2", estimated_credits=100.0
        )

    # Settle
    await budget.settle_budget(reservation_id=hold_id, actual_credits=15.0)
    # Non-existent settle should not fail
    await budget.settle_budget(reservation_id="unknown-hold", actual_credits=5.0)


def test_zero_cost_rate_model():
    """Verify rate model returns 0.0 credits."""
    model = ZeroCostRateModelAdapter()
    cost = model.calculate_estimated_cost(ResourceRequirements())
    assert cost == 0.0
