"""Unit tests for budget port models and contracts."""

import inspect

import pytest

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.ports.budget import (
    BudgetAccountingPort,
    CostRate,
    CostRateModelPort,
)


def test_cost_rate_valid():
    """Verify CostRate creation."""
    rate = CostRate(
        cpu_hour_credits=0.05,
        ram_gb_hour_credits=0.01,
        gpu_hour_credits=1.25,
        provider=CspProvider.AWS,
    )
    assert rate.cpu_hour_credits == 0.05
    assert rate.provider == CspProvider.AWS


def test_cost_rate_model_port_is_abstract() -> None:
    """Verify that CostRateModelPort cannot be instantiated directly and is abstract."""
    is_abs = inspect.isabstract(CostRateModelPort)
    assert is_abs is True
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        CostRateModelPort()  # ty: ignore[call-non-callable] # type: ignore[abstract]


def test_cost_rate_model_port_abstract_methods() -> None:
    """Verify abstract methods on CostRateModelPort."""
    expected = {"calculate_actual_cost", "calculate_estimated_cost"}
    abstracts = CostRateModelPort.__abstractmethods__
    diff = expected.difference(abstracts)
    assert len(diff) == 0


def test_budget_accounting_port_is_abstract() -> None:
    """Verify that BudgetAccountingPort cannot be instantiated directly and is abstract."""
    is_abs = inspect.isabstract(BudgetAccountingPort)
    assert is_abs is True
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        BudgetAccountingPort()  # ty: ignore[call-non-callable] # type: ignore[abstract]


def test_budget_accounting_port_abstract_methods() -> None:
    """Verify abstract methods on BudgetAccountingPort."""
    expected = {
        "get_account",
        "release_budget",
        "reserve_budget",
        "settle_budget",
        "settle_segment",
    }
    abstracts = BudgetAccountingPort.__abstractmethods__
    diff = expected.difference(abstracts)
    assert len(diff) == 0
