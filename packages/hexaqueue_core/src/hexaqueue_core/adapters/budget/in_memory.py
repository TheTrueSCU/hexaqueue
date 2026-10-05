"""In-memory budget and zero-cost rate adapters."""

from collections import defaultdict
from uuid import uuid4

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.exceptions import QuotaExceededError
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.ports.budget import BudgetAccountingPort, CostRateModelPort


class InMemoryBudgetAccountingAdapter(BudgetAccountingPort):
    """In-memory budget reservation and credit tracking adapter."""

    def __init__(self, initial_balances: dict[str, float] | None = None) -> None:
        self._balances = defaultdict(lambda: 10000.0)
        if initial_balances:
            self._balances.update(initial_balances)
        self._holds: dict[str, tuple[str, float]] = {}

    async def reserve_budget(
        self, tenant_id: str, job_id: str, estimated_credits: float
    ) -> str:
        """Place budget hold."""
        if self._balances[tenant_id] < estimated_credits:
            msg = f"Insufficient credit balance for tenant '{tenant_id}'"
            raise QuotaExceededError(msg)
        self._balances[tenant_id] -= estimated_credits
        hold_id = f"hold-{uuid4().hex[:8]}"
        self._holds[hold_id] = (tenant_id, estimated_credits)
        return hold_id

    async def settle_budget(self, reservation_id: str, actual_credits: float) -> None:
        """Settle budget hold."""
        if reservation_id in self._holds:
            tenant_id, reserved = self._holds.pop(reservation_id)
            refund = reserved - actual_credits
            self._balances[tenant_id] += refund


class ZeroCostRateModelAdapter(CostRateModelPort):
    """Cost rate model adapter returning 0.0 credits for free-tier / local testing."""

    def calculate_estimated_cost(
        self,
        requirements: ResourceRequirements,
        provider: CspProvider = CspProvider.LOCAL,
    ) -> float:
        """Always return 0.0 credits for local zero-cost profile."""
        return 0.0


__all__ = [
    "InMemoryBudgetAccountingAdapter",
    "ZeroCostRateModelAdapter",
]
