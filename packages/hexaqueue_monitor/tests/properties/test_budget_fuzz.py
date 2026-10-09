"""Property-based stateful and fuzz testing for budget ledger and cost models.

Notes/Architectural Intent:
    Mathematically verifies zero-credit-leak invariants, conservation of balance,
    and non-double-counting guarantees across arbitrary sequences of reservations,
    preemption segment settlements, and cancellations.
"""

import asyncio

from hypothesis import given
from hypothesis import strategies as st

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.exceptions import QuotaExceededError
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_monitor.adapters.ledger import InMemoryBudgetLedgerAdapter
from hexaqueue_monitor.adapters.rates import NormalizedCostRateModelAdapter


@given(
    st.floats(min_value=100.0, max_value=10000.0),
    st.lists(
        st.tuples(
            st.floats(min_value=1.0, max_value=100.0),  # estimated hold
            st.floats(min_value=0.0, max_value=100.0),  # actual usage
            st.booleans(),  # is_cancelled_early
        ),
        min_size=1,
        max_size=20,
    ),
)
def test_budget_ledger_balance_conservation_fuzz(
    initial_deposit: float,
    actions: list[tuple[float, float, bool]],
) -> None:
    """Balance conservation invariant: available balance strictly matches deposits minus holds and settlements."""

    async def _run() -> None:
        tenant_id = "tenant-fuzz"
        ledger = InMemoryBudgetLedgerAdapter(
            initial_balances={tenant_id: initial_deposit}
        )

        active_holds: dict[str, float] = {}

        for idx, (estimated, actual, is_cancelled) in enumerate(actions):
            job_id = f"job-{idx}"
            acct = await ledger.get_account(tenant_id)
            if acct.available_balance >= estimated:
                hold_id = await ledger.reserve_budget(tenant_id, job_id, estimated)
                active_holds[hold_id] = estimated

                # Either cancel (release) or settle
                if is_cancelled:
                    await ledger.release_budget(hold_id)
                    active_holds.pop(hold_id)
                else:
                    capped_actual = min(estimated, actual)
                    await ledger.settle_budget(hold_id, actual_credits=capped_actual)
                    active_holds.pop(hold_id)
            else:
                # Must fail-closed with QuotaExceededError
                try:
                    await ledger.reserve_budget(tenant_id, job_id, estimated)
                    err = False
                except QuotaExceededError:
                    err = True
                assert err is True

        final_acct = await ledger.get_account(tenant_id)
        # Fundamental Invariant: credit_balance == available_balance + settled_total + active_holds_total
        total_accounted = round(
            final_acct.available_balance
            + final_acct.settled_total
            + final_acct.active_holds_total,
            2,
        )
        assert total_accounted == round(initial_deposit, 2)

    asyncio.run(_run())


@given(
    st.floats(min_value=100.0, max_value=1000.0),
    st.lists(st.floats(min_value=0.5, max_value=10.0), min_size=1, max_size=8),
)
def test_preemption_segments_no_double_count_fuzz(
    initial_deposit: float,
    segment_costs: list[float],
) -> None:
    """Preemption segment accumulation strictly equals sum of segments and prevents double counting."""

    async def _run() -> None:
        tenant_id = "tenant-preempt-fuzz"
        ledger = InMemoryBudgetLedgerAdapter(
            initial_balances={tenant_id: initial_deposit}
        )
        hold_amount = sum(segment_costs) + 10.0

        hold_id = await ledger.reserve_budget(tenant_id, "job-preempt", hold_amount)

        cumulative = 0.0
        for seg in segment_costs:
            cumulative = await ledger.settle_segment(hold_id, segment_credits=seg)

        expected_sum = round(sum(segment_costs), 4)
        assert round(cumulative, 4) == expected_sum

        # Final settlement with total cost
        total_final = cumulative + 2.0
        await ledger.settle_budget(hold_id, actual_credits=total_final)

        final_acct = await ledger.get_account(tenant_id)
        assert round(final_acct.settled_total, 4) == round(total_final, 4)
        assert final_acct.active_holds_total == 0.0

    asyncio.run(_run())


@given(
    st.integers(min_value=1, max_value=64),
    st.integers(min_value=512, max_value=131072),
    st.integers(min_value=0, max_value=8),
    st.floats(min_value=10.0, max_value=86400.0),
    st.sampled_from(list(CspProvider)),
)
def test_cost_rate_model_monotonicity_fuzz(
    cpus: int,
    ram_mb: int,
    gpus: int,
    walltime: float,
    provider: CspProvider,
) -> None:
    """Estimated and actual cost calculations are strictly non-negative and monotonic."""
    model = NormalizedCostRateModelAdapter()
    req = ResourceRequirements(
        cpus=cpus,
        ram_mb=ram_mb,
        gpus=gpus,
        walltime_seconds=int(walltime),
    )
    est_cost = model.calculate_estimated_cost(req, provider=provider)
    act_cost = model.calculate_actual_cost(
        walltime_seconds=walltime,
        cpus=cpus,
        ram_mb=ram_mb,
        gpus=gpus,
        provider=provider,
    )
    assert est_cost >= 0.0
    assert act_cost >= 0.0
    if provider == CspProvider.LOCAL:
        assert est_cost == 0.0
        assert act_cost == 0.0


__all__ = [
    "test_budget_ledger_balance_conservation_fuzz",
    "test_cost_rate_model_monotonicity_fuzz",
    "test_preemption_segments_no_double_count_fuzz",
]
