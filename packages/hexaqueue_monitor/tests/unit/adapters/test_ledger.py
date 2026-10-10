"""Unit tests for InMemoryBudgetLedgerAdapter.

Notes/Architectural Intent:
    Tests two-phase reservations, segment preemption settlements, zero-run cancellation releases,
    stale reservation auto-expiry, and non-double-counting guarantees.
"""

import pytest

from hexaqueue_core.domain.exceptions import QuotaExceededError
from hexaqueue_monitor.adapters.ledger import InMemoryBudgetLedgerAdapter


@pytest.mark.asyncio
async def test_budget_ledger_two_phase_lifecycle() -> None:
    """Verify hold reservation, settlement, and balance reconciliation."""
    ledger = InMemoryBudgetLedgerAdapter(initial_balances={"acct-1": 100.0})
    hold_id = await ledger.reserve_budget("acct-1", "job-1", estimated_credits=30.0)

    acct_after_hold = await ledger.get_account("acct-1")
    assert acct_after_hold.active_holds_total == 30.0
    assert acct_after_hold.available_balance == 70.0

    # Settle job that ran and used 20.0 credits (10.0 refunded)
    await ledger.settle_budget(hold_id, actual_credits=20.0)

    acct_settled = await ledger.get_account("acct-1")
    assert acct_settled.active_holds_total == 0.0
    assert acct_settled.settled_total == 20.0
    assert acct_settled.available_balance == 80.0


@pytest.mark.asyncio
async def test_budget_ledger_insufficient_credits() -> None:
    """Verify QuotaExceededError when requesting more credits than available."""
    ledger = InMemoryBudgetLedgerAdapter(initial_balances={"acct-poor": 10.0})
    with pytest.raises(QuotaExceededError):
        await ledger.reserve_budget(
            "acct-poor", "job-expensive", estimated_credits=25.0
        )


@pytest.mark.asyncio
async def test_budget_ledger_segmented_preemption_no_double_counting() -> None:
    """Verify preemption segments accumulate and do not double count on final completion."""
    ledger = InMemoryBudgetLedgerAdapter(initial_balances={"acct-preempt": 100.0})
    hold_id = await ledger.reserve_budget(
        "acct-preempt", "job-preemptible", estimated_credits=50.0
    )

    # Preemption 1 after consuming 12.0 credits
    cum1 = await ledger.settle_segment(hold_id, segment_credits=12.0)
    assert cum1 == 12.0

    acct_seg1 = await ledger.get_account("acct-preempt")
    assert acct_seg1.settled_total == 12.0
    # Remaining hold = 50 - 12 = 38
    assert acct_seg1.active_holds_total == 38.0
    assert acct_seg1.available_balance == 50.0

    # Preemption 2 after consuming another 18.0 credits (total so far = 30.0)
    cum2 = await ledger.settle_segment(hold_id, segment_credits=18.0)
    assert cum2 == 30.0

    acct_seg2 = await ledger.get_account("acct-preempt")
    assert acct_seg2.settled_total == 30.0
    assert acct_seg2.active_holds_total == 20.0
    assert acct_seg2.available_balance == 50.0

    # Job resumes and completes. Total job walltime consumption = 35.0 credits.
    # Final settlement passes actual_credits=35.0 (total job cost).
    # Incremental delta to settle must be 35.0 - 30.0 = 5.0, NOT 35.0!
    await ledger.settle_budget(hold_id, actual_credits=35.0)

    acct_final = await ledger.get_account("acct-preempt")
    assert acct_final.settled_total == 35.0
    assert acct_final.active_holds_total == 0.0
    assert acct_final.available_balance == 65.0


@pytest.mark.asyncio
async def test_budget_ledger_zero_run_cancellation_release() -> None:
    """Verify cancelling an un-run job releases 100% of held credits with zero leak."""
    ledger = InMemoryBudgetLedgerAdapter(initial_balances={"acct-cancel": 200.0})
    hold_id = await ledger.reserve_budget(
        "acct-cancel", "job-unrun", estimated_credits=80.0
    )

    acct_held = await ledger.get_account("acct-cancel")
    assert acct_held.available_balance == 120.0

    await ledger.release_budget(hold_id)

    acct_released = await ledger.get_account("acct-cancel")
    assert acct_released.available_balance == 200.0
    assert acct_released.active_holds_total == 0.0
    assert acct_released.settled_total == 0.0


@pytest.mark.asyncio
async def test_budget_ledger_stale_reservation_expiration() -> None:
    """Verify expiring stale reservations transitions state to EXPIRED and restores balance."""
    ledger = InMemoryBudgetLedgerAdapter(initial_balances={"acct-stale": 100.0})
    hold_id = await ledger.reserve_budget(
        "acct-stale", "job-stale", estimated_credits=40.0
    )

    # Sweep with 0.0 max age to force immediate expiration
    expired = await ledger.expire_stale_reservations(max_age_seconds=0.0)
    assert hold_id in expired

    acct_reclaimed = await ledger.get_account("acct-stale")
    assert acct_reclaimed.available_balance == 100.0
    assert acct_reclaimed.active_holds_total == 0.0


@pytest.mark.asyncio
async def test_budget_ledger_expired_reservation_settlement() -> None:
    """Verify an expired reservation can still be settled upon job completion."""
    ledger = InMemoryBudgetLedgerAdapter(initial_balances={"acct-exp": 100.0})
    hold_id = await ledger.reserve_budget(
        "acct-exp", "job-long", estimated_credits=30.0
    )

    # Force expiration of hold
    expired = await ledger.expire_stale_reservations(max_age_seconds=0.0)
    assert hold_id in expired

    # Job finishes and settles 25.0 credits
    await ledger.settle_budget(hold_id, actual_credits=25.0)

    acct = await ledger.get_account("acct-exp")
    bal = acct.available_balance
    settled = acct.settled_total
    holds = acct.active_holds_total
    assert settled == 25.0
    assert holds == 0.0
    assert bal == 75.0


@pytest.mark.asyncio
async def test_budget_ledger_deposit() -> None:
    """Verify depositing funds increases available credit balance."""
    ledger = InMemoryBudgetLedgerAdapter(initial_balances={"acct-deposit": 50.0})
    acct = await ledger.deposit("acct-deposit", amount=150.0)
    bal = acct.credit_balance
    avail = acct.available_balance
    assert bal == 200.0
    assert avail == 200.0

    with pytest.raises(ValueError, match="positive"):
        await ledger.deposit("acct-deposit", amount=-10.0)


@pytest.mark.asyncio
async def test_budget_ledger_oversettled_segment_clamping() -> None:
    """Verify an over-settled reservation segment clamps to zero and does not cancel other holds."""
    ledger = InMemoryBudgetLedgerAdapter(initial_balances={"acct-clamp": 100.0})
    hold_a = await ledger.reserve_budget("acct-clamp", "job-a", estimated_credits=10.0)
    hold_b = await ledger.reserve_budget("acct-clamp", "job-b", estimated_credits=40.0)
    assert hold_b.startswith("hold-")

    # Settle 50.0 segment on hold A (which held 10.0)
    await ledger.settle_segment(hold_a, segment_credits=50.0)

    acct = await ledger.get_account("acct-clamp")
    # Hold A has remaining hold clamped to max(0, 10 - 50) = 0.0
    # Hold B has remaining hold = 40.0
    # Total active holds must be 40.0, NOT 0.0!
    holds = acct.active_holds_total
    settled = acct.settled_total
    bal = acct.available_balance
    assert holds == 40.0
    assert settled == 50.0
    assert bal == 10.0


__all__ = [
    "test_budget_ledger_deposit",
    "test_budget_ledger_expired_reservation_settlement",
    "test_budget_ledger_insufficient_credits",
    "test_budget_ledger_oversettled_segment_clamping",
    "test_budget_ledger_segmented_preemption_no_double_counting",
    "test_budget_ledger_stale_reservation_expiration",
    "test_budget_ledger_two_phase_lifecycle",
    "test_budget_ledger_zero_run_cancellation_release",
]
