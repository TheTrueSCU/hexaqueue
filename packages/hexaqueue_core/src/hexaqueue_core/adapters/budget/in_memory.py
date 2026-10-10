"""In-memory budget and zero-cost rate adapters.

Notes/Architectural Intent:
    Provides an in-memory two-phase budget reservation ledger supporting atomic holds,
    partial cancellation releases, and segmented preemption settlement without double counting.
"""

from collections import defaultdict
from uuid import uuid4

from hexaqueue_core.domain.budget import (
    BudgetReservation,
    ReservationState,
    TenantAccount,
)
from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.exceptions import HexaqueueError, QuotaExceededError
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.ports.budget import BudgetAccountingPort, CostRateModelPort


class InMemoryBudgetAccountingAdapter(BudgetAccountingPort):
    """In-memory budget reservation and credit tracking adapter.

    Args:
        initial_balances: Optional map of initial tenant balances.
    """

    def __init__(self, initial_balances: dict[str, float] | None = None) -> None:
        self._deposits: dict[str, float] = defaultdict(lambda: 10000.0)
        if initial_balances:
            self._deposits.update(initial_balances)
        self._reservations: dict[str, BudgetReservation] = {}
        self._settled_by_tenant: dict[str, float] = defaultdict(float)

    async def reserve_budget(
        self, tenant_id: str, job_id: str, estimated_credits: float
    ) -> str:
        """Place pre-emptive budget hold for job execution.

        Args:
            tenant_id: Target tenant account.
            job_id: Job identifier.
            estimated_credits: Maximum credits to hold.

        Returns:
            Reservation identifier.

        Raises:
            QuotaExceededError: If tenant balance is insufficient.
        """
        account = await self.get_account(tenant_id)
        if account.available_balance < estimated_credits:
            msg = f"Insufficient credit balance for tenant '{tenant_id}'"
            raise QuotaExceededError(msg)

        hold_id = f"hold-{uuid4().hex[:8]}"
        res = BudgetReservation(
            reservation_id=hold_id,
            tenant_id=tenant_id,
            job_id=job_id,
            held_credits=estimated_credits,
            state=ReservationState.ACTIVE,
        )
        self._reservations[hold_id] = res
        return hold_id

    async def settle_budget(
        self,
        reservation_id: str,
        actual_credits: float,
        tenant_id: str | None = None,
    ) -> None:
        """Finalize budget settlement for a finished or cancelled job.

        Args:
            reservation_id: Target reservation identifier.
            actual_credits: Final credits consumed by the job.
            tenant_id: Optional tenant identifier to enforce reservation ownership.

        Raises:
            HexaqueueError: If reservation ID is invalid or already finalized.
        """
        if reservation_id not in self._reservations:
            return

        res = self._reservations[reservation_id]
        if tenant_id is not None and res.tenant_id != tenant_id:
            msg = f"Tenant '{tenant_id}' does not own reservation '{reservation_id}'"
            raise HexaqueueError(msg)

        if res.state not in (ReservationState.ACTIVE, ReservationState.EXPIRED):
            msg = f"Reservation '{reservation_id}' already in terminal state '{res.state}'"
            raise HexaqueueError(msg)

        delta = max(0.0, actual_credits - res.settled_credits)
        settled_res = res.finalize_settlement(actual_credits)
        self._reservations[reservation_id] = settled_res
        self._settled_by_tenant[res.tenant_id] += delta

    async def settle_segment(
        self,
        reservation_id: str,
        segment_credits: float,
        tenant_id: str | None = None,
    ) -> float:
        """Settle an incremental execution segment upon preemption without closing reservation.

        Args:
            reservation_id: Target reservation identifier.
            segment_credits: Credits consumed during this execution segment.
            tenant_id: Optional tenant identifier to enforce reservation ownership.

        Returns:
            Cumulative credits settled across segments for this reservation.

        Raises:
            HexaqueueError: If reservation ID is invalid or already finalized.
        """
        if reservation_id not in self._reservations:
            msg = f"Reservation '{reservation_id}' not found"
            raise HexaqueueError(msg)

        res = self._reservations[reservation_id]
        if tenant_id is not None and res.tenant_id != tenant_id:
            msg = f"Tenant '{tenant_id}' does not own reservation '{reservation_id}'"
            raise HexaqueueError(msg)

        if res.state != ReservationState.ACTIVE:
            msg = f"Cannot settle segment on inactive reservation '{reservation_id}'"
            raise HexaqueueError(msg)

        updated_res = res.settle_segment(segment_credits)
        self._reservations[reservation_id] = updated_res
        self._settled_by_tenant[res.tenant_id] += segment_credits
        return updated_res.settled_credits

    async def release_budget(
        self,
        reservation_id: str,
        tenant_id: str | None = None,
    ) -> None:
        """Release an active budget hold in full without billing.

        Args:
            reservation_id: Target reservation identifier.
            tenant_id: Optional tenant identifier to enforce reservation ownership.

        Raises:
            HexaqueueError: If reservation ID is invalid or already finalized.
        """
        if reservation_id not in self._reservations:
            msg = f"Reservation '{reservation_id}' not found"
            raise HexaqueueError(msg)

        res = self._reservations[reservation_id]
        if tenant_id is not None and res.tenant_id != tenant_id:
            msg = f"Tenant '{tenant_id}' does not own reservation '{reservation_id}'"
            raise HexaqueueError(msg)

        if res.state != ReservationState.ACTIVE:
            msg = (
                f"Cannot release reservation '{reservation_id}' in state '{res.state}'"
            )
            raise HexaqueueError(msg)

        self._reservations[reservation_id] = res.release()

    async def get_account(self, tenant_id: str) -> TenantAccount:
        """Retrieve tenant credit balance and active hold details.

        Args:
            tenant_id: Tenant or project account identifier.

        Returns:
            TenantAccount entity with balance and hold metrics.
        """
        deposit = self._deposits[tenant_id]
        settled = self._settled_by_tenant[tenant_id]
        active_holds = sum(
            max(0.0, r.held_credits - r.settled_credits)
            for r in self._reservations.values()
            if r.tenant_id == tenant_id and r.state == ReservationState.ACTIVE
        )
        return TenantAccount(
            tenant_id=tenant_id,
            credit_balance=deposit,
            active_holds_total=max(0.0, active_holds),
            settled_total=settled,
        )


class ZeroCostRateModelAdapter(CostRateModelPort):
    """Cost rate model adapter returning 0.0 credits for free-tier / local testing."""

    def calculate_estimated_cost(
        self,
        requirements: ResourceRequirements,
        provider: CspProvider = CspProvider.LOCAL,
    ) -> float:
        """Always return 0.0 credits for local zero-cost profile.

        Args:
            requirements: Job resource requirements.
            provider: Target CSP provider.

        Returns:
            0.0 credits.
        """
        return 0.0

    def calculate_actual_cost(
        self,
        walltime_seconds: float,
        cpus: int = 1,
        ram_mb: int = 1024,
        gpus: int = 0,
        provider: CspProvider = CspProvider.LOCAL,
    ) -> float:
        """Always return 0.0 credits for zero-cost profile.

        Args:
            walltime_seconds: Elapsed execution duration in seconds.
            cpus: Assigned CPU core count.
            ram_mb: Consumed RAM in megabytes.
            gpus: Assigned GPU accelerator count.
            provider: Target cloud provider.

        Returns:
            0.0 credits.
        """
        return 0.0


__all__ = [
    "InMemoryBudgetAccountingAdapter",
    "ZeroCostRateModelAdapter",
]
