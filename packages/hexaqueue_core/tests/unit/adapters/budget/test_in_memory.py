"""Unit tests for in-memory budget accounting and rate model adapters."""

import pytest

from hexaqueue_core.adapters.budget.in_memory import (
    InMemoryBudgetAccountingAdapter,
    ZeroCostRateModelAdapter,
)
from hexaqueue_core.domain.exceptions import QuotaExceededError
from hexaqueue_core.domain.resources import ResourceRequirements


@pytest.mark.asyncio
async def test_mock_budget_accounting_and_rate_model():
    """Verify two-phase budget reservation, settle, and rate calculation."""
    rate_model = ZeroCostRateModelAdapter()
    estimated = rate_model.calculate_estimated_cost(ResourceRequirements())
    assert estimated == 0.0

    budget = InMemoryBudgetAccountingAdapter(initial_balances={"tenant-1": 100.0})
    hold_id = await budget.reserve_budget(
        tenant_id="tenant-1", job_id="j1", estimated_credits=50.0
    )
    assert hold_id.startswith("hold-")

    with pytest.raises(QuotaExceededError, match="Insufficient credit balance"):
        await budget.reserve_budget(
            tenant_id="tenant-1", job_id="j2", estimated_credits=60.0
        )

    await budget.settle_budget(reservation_id=hold_id, actual_credits=30.0)
