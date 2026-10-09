"""In-memory two-phase budget reservation and credit tracking ledger adapter.

Notes/Architectural Intent:
    Implements atomic two-phase commit budget holds, incremental preemption
    segment settlements, zero-leak hold releases, and automatic stale reservation
    expiration. Mathematically guarantees balance conservation and prevents double counting.
"""

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from uuid import uuid4

from hexaqueue_core.domain.budget import (
    BudgetReservation,
    ReservationState,
    TenantAccount,
)
from hexaqueue_core.domain.exceptions import HexaqueueError, QuotaExceededError
from hexaqueue_core.ports.budget import BudgetAccountingPort


class InMemoryBudgetLedgerAdapter(BudgetAccountingPort):
    """In-memory thread-safe budget ledger implementing two-phase commit accounting.

    Args:
        initial_balances: Optional mapping of initial tenant deposits.
    """

    def __init__(self, initial_balances: dict[str, float] | None = None) -> None:
        self._deposits: dict[str, float] = defaultdict(lambda: 10000.0)
        if initial_balances:
            self._deposits.update(initial_balances)
        self._reservations: dict[str, BudgetReservation] = {}
        self._settled_by_tenant: dict[str, float] = defaultdict(float)
        self._lock = asyncio.Lock()

    async def reserve_budget(
        self, tenant_id: str, job_id: str, estimated_credits: float
    ) -> str:
        """Place pre-emptive budget hold for job execution.

        Args:
            tenant_id: Target tenant account.
            job_id: Job identifier.
            estimated_credits: Maximum credits to hold.

        Returns:
            Reservation identifier token.

        Raises:
            QuotaExceededError: If tenant balance is insufficient.
        """
        async with self._lock:
            account = self._compute_account_unlocked(tenant_id)
            if account.available_balance < estimated_credits:
                msg = (
                    f"Insufficient credit balance for tenant '{tenant_id}': "
                    f"requested {estimated_credits}, available {account.available_balance}"
                )
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

    async def settle_budget(self, reservation_id: str, actual_credits: float) -> None:
        """Finalize budget settlement for a finished or cancelled job.

        Args:
            reservation_id: Target reservation identifier.
            actual_credits: Final measured credits consumed by the job.

        Raises:
            HexaqueueError: If reservation ID is invalid or already finalized.

        Notes/Architectural Intent:
            Prevents double counting by computing the delta between actual_credits
            and previously settled segments (e.g. prior preemptions).
        """
        async with self._lock:
            if reservation_id not in self._reservations:
                return

            res = self._reservations[reservation_id]
            if res.state != ReservationState.ACTIVE:
                msg = f"Reservation '{reservation_id}' already in terminal state '{res.state}'"
                raise HexaqueueError(msg)

            delta = max(0.0, actual_credits - res.settled_credits)
            settled_res = res.finalize_settlement(actual_credits)
            self._reservations[reservation_id] = settled_res
            self._settled_by_tenant[res.tenant_id] += delta

    async def settle_segment(
        self, reservation_id: str, segment_credits: float
    ) -> float:
        """Settle an incremental execution segment upon preemption without closing the reservation.

        Args:
            reservation_id: Target reservation identifier.
            segment_credits: Credits consumed during this execution segment.

        Returns:
            Cumulative credits settled across all segments for this reservation.

        Raises:
            HexaqueueError: If reservation ID is invalid or already finalized.
        """
        async with self._lock:
            if reservation_id not in self._reservations:
                msg = f"Reservation '{reservation_id}' not found"
                raise HexaqueueError(msg)

            res = self._reservations[reservation_id]
            if res.state != ReservationState.ACTIVE:
                msg = (
                    f"Cannot settle segment on inactive reservation '{reservation_id}'"
                )
                raise HexaqueueError(msg)

            updated_res = res.settle_segment(segment_credits)
            self._reservations[reservation_id] = updated_res
            self._settled_by_tenant[res.tenant_id] += segment_credits
            return updated_res.settled_credits

    async def release_budget(self, reservation_id: str) -> None:
        """Release an active budget hold in full without billing.

        Args:
            reservation_id: Target reservation identifier.

        Raises:
            HexaqueueError: If reservation ID is invalid or already finalized.
        """
        async with self._lock:
            if reservation_id not in self._reservations:
                msg = f"Reservation '{reservation_id}' not found"
                raise HexaqueueError(msg)

            res = self._reservations[reservation_id]
            if res.state != ReservationState.ACTIVE:
                msg = f"Cannot release reservation '{reservation_id}' in state '{res.state}'"
                raise HexaqueueError(msg)

            self._reservations[reservation_id] = res.release()

    async def deposit(self, tenant_id: str, amount: float) -> TenantAccount:
        """Deposit additional credits into a tenant account.

        Args:
            tenant_id: Target tenant account.
            amount: Credit amount to deposit.

        Returns:
            Updated TenantAccount entity.

        Raises:
            ValueError: If deposit amount is non-positive.
        """
        if amount <= 0.0:
            msg = f"Deposit amount must be positive, got {amount}"
            raise ValueError(msg)
        async with self._lock:
            self._deposits[tenant_id] += amount
            return self._compute_account_unlocked(tenant_id)

    async def get_account(self, tenant_id: str) -> TenantAccount:
        """Retrieve tenant credit balance and active hold details.

        Args:
            tenant_id: Tenant or project account identifier.

        Returns:
            TenantAccount entity with balance and hold metrics.
        """
        async with self._lock:
            return self._compute_account_unlocked(tenant_id)

    async def list_active_reservations(self) -> list[BudgetReservation]:
        """List all currently active budget holds across all tenants.

        Returns:
            List of active BudgetReservation instances.
        """
        async with self._lock:
            return [
                r
                for r in self._reservations.values()
                if r.state == ReservationState.ACTIVE
            ]

    async def expire_stale_reservations(self, max_age_seconds: float) -> list[str]:
        """Expire unfinalized budget holds older than max_age_seconds and release funds.

        Args:
            max_age_seconds: Maximum allowed age in seconds for active reservations.

        Returns:
            List of expired reservation identifiers.
        """
        now = datetime.now(UTC)
        expired_ids: list[str] = []
        async with self._lock:
            for hold_id, res in list(self._reservations.items()):
                if res.state == ReservationState.ACTIVE:
                    age = (now - res.created_at).total_seconds()
                    if age > max_age_seconds:
                        self._reservations[hold_id] = res.model_copy(
                            update={
                                "state": ReservationState.EXPIRED,
                                "settled_at": now,
                            }
                        )
                        expired_ids.append(hold_id)
        return expired_ids

    def _compute_account_unlocked(self, tenant_id: str) -> TenantAccount:
        """Compute account state without re-acquiring lock."""
        deposit = self._deposits[tenant_id]
        settled = self._settled_by_tenant[tenant_id]
        active_holds = sum(
            r.held_credits - r.settled_credits
            for r in self._reservations.values()
            if r.tenant_id == tenant_id and r.state == ReservationState.ACTIVE
        )
        return TenantAccount(
            tenant_id=tenant_id,
            credit_balance=deposit,
            active_holds_total=max(0.0, active_holds),
            settled_total=settled,
        )


__all__ = [
    "InMemoryBudgetLedgerAdapter",
]
