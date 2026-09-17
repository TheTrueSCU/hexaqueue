"""Unit tests for multi-factor priority aging and JobPriorityCalculator."""

from datetime import UTC, datetime, timedelta

import pytest

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.priority import (
    JobPriorityCalculator,
    PriorityWeights,
)


def test_priority_weights_validation() -> None:
    """Verify PriorityWeights invariants and validation."""
    weights = PriorityWeights()
    res_age = weights.weight_age
    assert res_age == 1000.0
    res_fs = weights.weight_fairshare
    assert res_fs == 10000.0
    res_base = weights.weight_base_priority
    assert res_base == 10.0
    res_max_age = weights.max_age_seconds
    assert res_max_age == 86400.0

    with pytest.raises(
        ValueError, match="At least one priority weight must be non-zero"
    ):
        PriorityWeights(weight_age=0.0, weight_fairshare=0.0, weight_base_priority=0.0)

    with pytest.raises(ValueError):
        PriorityWeights(max_age_seconds=0.0)


def test_priority_calculation_age_ramping() -> None:
    """Verify waiting time translates to a monotonic age factor bounded at 1.0."""
    calc = JobPriorityCalculator(
        weights=PriorityWeights(
            weight_age=1000.0,
            weight_fairshare=0.0,
            weight_base_priority=0.0,
            max_age_seconds=100.0,
        )
    )

    t0 = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)
    t0_secs = t0.timestamp()

    job = JobSpec(
        id="j1",
        run_id="r1",
        name="task",
        command="echo 1",
        created_at=t0,
    )

    # 1. At t0: wait_time = 0 -> age_factor = 0.0 -> priority = 0.0
    prio_0, age_0 = calc.calculate_effective_priority(job, current_timestamp=t0_secs)
    assert age_0 == 0.0
    assert prio_0 == 0.0

    # 2. At t0 + 50s: wait_time = 50s (50% of 100s) -> age_factor = 0.5 -> priority = 500.0
    prio_50, age_50 = calc.calculate_effective_priority(
        job, current_timestamp=t0_secs + 50.0
    )
    assert age_50 == 0.5
    assert prio_50 == 500.0

    # 3. At t0 + 100s: wait_time = 100s (100%) -> age_factor = 1.0 -> priority = 1000.0
    prio_100, age_100 = calc.calculate_effective_priority(
        job, current_timestamp=t0_secs + 100.0
    )
    assert age_100 == 1.0
    assert prio_100 == 1000.0

    # 4. At t0 + 500s: capped at 1.0 -> priority = 1000.0
    prio_500, age_500 = calc.calculate_effective_priority(
        job, current_timestamp=t0_secs + 500.0
    )
    assert age_500 == 1.0
    assert prio_500 == 1000.0


def test_priority_calculation_composite_and_bonus() -> None:
    """Verify combination of fairshare, base priority, and compensatory preemption bonus."""
    calc = JobPriorityCalculator(
        weights=PriorityWeights(
            weight_age=1000.0,
            weight_fairshare=5000.0,
            weight_base_priority=10.0,
            max_age_seconds=1000.0,
        )
    )

    t0 = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)
    t0_secs = t0.timestamp()

    # Base priority: 200 -> 200 * 10 = 2000
    # Fairshare factor: 0.8 -> 0.8 * 5000 = 4000
    # Wait time: 200s -> age_factor = 0.2 -> 0.2 * 1000 = 200
    # Priority bonus: 500
    # Expected: 2000 + 4000 + 200 + 500 = 6700
    job = JobSpec(
        id="j-bonus",
        run_id="r1",
        name="task",
        command="echo 1",
        priority=200,
        priority_bonus=500.0,
        created_at=t0,
    )

    prio, age_factor = calc.calculate_effective_priority(
        job=job,
        current_timestamp=t0_secs + 200.0,
        fairshare_factor=0.8,
    )
    assert age_factor == 0.2
    assert prio == 6700.0


def test_rank_jobs_deterministic_ordering_and_tie_breaking() -> None:
    """Verify rank_jobs sorts by descending priority, then FIFO, then ID."""
    calc = JobPriorityCalculator(
        weights=PriorityWeights(
            weight_age=0.0,
            weight_fairshare=1000.0,
            weight_base_priority=10.0,
        )
    )

    t0 = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)
    t0_secs = t0.timestamp()

    # Job 1: High fair-share user (factor 1.0), base priority 100 -> 1000 + 1000 = 2000
    j1 = JobSpec(
        id="j-under-quota",
        run_id="r1",
        name="t1",
        command="ls",
        user="alice",
        priority=100,
        created_at=t0,
    )

    # Job 2: Low fair-share user (factor 0.2), base priority 100 -> 200 + 1000 = 1200
    j2 = JobSpec(
        id="j-over-quota",
        run_id="r1",
        name="t2",
        command="ls",
        user="bob",
        priority=100,
        created_at=t0 - timedelta(seconds=100),
    )

    # Job 3: Same effective priority as j1, but submitted later
    j3 = JobSpec(
        id="j-under-quota-later",
        run_id="r1",
        name="t3",
        command="ls",
        user="alice",
        priority=100,
        created_at=t0 + timedelta(seconds=5),
    )

    ranked = calc.rank_jobs(
        jobs=[j2, j3, j1],
        current_timestamp=t0_secs + 10.0,
        fairshare_factors={"alice": 1.0, "bob": 0.2},
    )

    assert len(ranked) == 3
    # j1 has prio 2000, created at t0 -> 1st
    res_1 = ranked[0].job.id
    assert res_1 == "j-under-quota"
    # j3 has prio 2000, created at t0+5s -> 2nd (FIFO tie-break)
    res_2 = ranked[1].job.id
    assert res_2 == "j-under-quota-later"
    # j2 has prio 1200 -> 3rd
    res_3 = ranked[2].job.id
    assert res_3 == "j-over-quota"
