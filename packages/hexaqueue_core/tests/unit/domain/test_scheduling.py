"""Unit tests for batch scheduling, backfill, and controlled preemption (Issue #8)."""

from datetime import UTC, datetime, timedelta

import pytest

from hexaqueue_core.domain.fairshare import FairShareNode, FairShareTree
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.priority import JobPriorityCalculator
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.scheduling import (
    BatchSchedulerEngine,
    ConservativeBackfillScheduler,
    ControlledPreemptionEngine,
    PreemptionPolicy,
    ResourceSlotPool,
)


def test_resource_slot_pool_accounting() -> None:
    """Verify ResourceSlotPool capacity tracking and allocation invariants."""
    pool = ResourceSlotPool(total_slots=4)
    res_total = pool.total_slots
    assert res_total == 4
    res_used_0 = pool.used_slots
    assert res_used_0 == 0
    res_avail_0 = pool.available_slots
    assert res_avail_0 == 4

    job_1cpu = JobSpec(
        id="j1",
        run_id="r1",
        name="task",
        command="ls",
        resources=ResourceRequirements(cpus=1),
    )
    job_2cpu = JobSpec(
        id="j2",
        run_id="r1",
        name="task",
        command="ls",
        resources=ResourceRequirements(cpus=2),
    )
    job_big = JobSpec(
        id="j-big",
        run_id="r1",
        name="task",
        command="ls",
        resources=ResourceRequirements(cpus=4),
    )

    fit_1 = pool.can_fit(job_1cpu)
    assert fit_1 is True
    alloc_1 = pool.allocate(job_1cpu)
    assert alloc_1 is True
    assert pool.used_slots == 1
    assert pool.available_slots == 3

    alloc_2 = pool.allocate(job_2cpu)
    assert alloc_2 is True
    res_used_2 = pool.used_slots
    assert res_used_2 == 3
    res_avail_2 = pool.available_slots
    assert res_avail_2 == 1

    # Cannot fit job_big (requires 4, only 1 available)
    fit_big = pool.can_fit(job_big)
    assert fit_big is False
    alloc_big = pool.allocate(job_big)
    assert alloc_big is False

    # Release j1 (1 cpu released -> 2 cpus remain allocated -> 2 available)
    rel_1 = pool.release("j1")
    assert rel_1 is True
    res_avail_rel1 = pool.available_slots
    assert res_avail_rel1 == 2

    # Release non-existent
    rel_ghost = pool.release("ghost")
    assert rel_ghost is False

    with pytest.raises(ValueError, match="must be positive"):
        ResourceSlotPool(total_slots=0)


def test_preemption_candidate_selection_ranking() -> None:
    """Verify lowest-impact preemption candidate selection order."""
    engine = ControlledPreemptionEngine(PreemptionPolicy(grace_period_seconds=10.0))
    t0 = 1000.0

    # User A has 3 running jobs:
    # j1: Not checkpointable, started at t0 - 100s (older)
    # j2: Not checkpointable, started at t0 - 10s (younger)
    # j3: Checkpointable, started at t0 - 50s
    j1 = JobSpec(
        id="j1",
        run_id="r1",
        name="old",
        command="ls",
        user="user_a",
        checkpointable=False,
    )
    j2 = JobSpec(
        id="j2",
        run_id="r1",
        name="young",
        command="ls",
        user="user_a",
        checkpointable=False,
    )
    j3 = JobSpec(
        id="j3",
        run_id="r1",
        name="chkpt",
        command="ls",
        user="user_a",
        checkpointable=True,
    )
    running = [j1, j2, j3]
    start_times = {"j1": t0 - 100.0, "j2": t0 - 10.0, "j3": t0 - 50.0}

    # 1. Candidate must be j3 because checkpointable jobs are prioritized first
    cand_1 = engine.select_preemption_candidate(
        running_jobs=running,
        starved_user="user_b",
        current_timestamp=t0,
        start_times=start_times,
    )
    assert cand_1 is not None
    assert cand_1.id == "j3"

    # 2. When neither is checkpointable, prefer younger job (j2 over j1)
    cand_2 = engine.select_preemption_candidate(
        running_jobs=[j1, j2],
        starved_user="user_b",
        current_timestamp=t0,
        start_times=start_times,
    )
    assert cand_2 is not None
    assert cand_2.id == "j2"

    # 3. Cannot preempt a job from the starved user themselves
    cand_none = engine.select_preemption_candidate(
        running_jobs=[j1],
        starved_user="user_a",
        current_timestamp=t0,
        start_times=start_times,
    )
    assert cand_none is None


def test_conservative_backfill_scheduling() -> None:
    """Verify backfill scheduler slots small jobs without delaying priority anchor."""
    pool = ResourceSlotPool(total_slots=4)
    # 2 slots occupied, 2 slots idle
    j_running = JobSpec(
        id="j-run",
        run_id="r1",
        name="t",
        command="ls",
        resources=ResourceRequirements(cpus=2),
    )
    pool.allocate(j_running)
    assert pool.available_slots == 2

    # Backfill candidates:
    # j_short: requires 2 slots, duration 30s (fits within 60s window)
    # j_long: requires 2 slots, duration 120s (exceeds window, rejected)
    j_short = JobSpec(
        id="j-short",
        run_id="r1",
        name="short",
        command="ls",
        resources=ResourceRequirements(cpus=2),
    )
    j_long = JobSpec(
        id="j-long",
        run_id="r1",
        name="long",
        command="ls",
        resources=ResourceRequirements(cpus=2),
    )

    scheduler = ConservativeBackfillScheduler()
    calc = JobPriorityCalculator()
    ranked_candidates = calc.rank_jobs([j_long, j_short], current_timestamp=1000.0)

    backfilled = scheduler.evaluate_backfill(
        unallocated_pending=ranked_candidates,
        pool=pool,
        anchor_reservation_window=60.0,
        job_durations={"j-short": 30.0, "j-long": 120.0},
    )

    assert len(backfilled) == 1
    assert backfilled[0].id == "j-short"
    assert pool.available_slots == 0


def test_the_100_slot_monopoly_thought_experiment() -> None:
    """Verify resolution of the classic 100-slot monopoly problem via controlled preemption.

    Scenario:
        - 100 slots in cluster pool.
        - User A holds 100% entitlement initially and submits 100 jobs filling the entire cluster.
        - User B (with 50% target entitlement) submits jobs but is initially starved (0 slots).
        - Before grace period (30s): no preemption occurs, jobs wait.
        - After grace period (35s): scheduler preemption triggers, preempts the youngest job
          from User A, grants compensation bonus, and dispatches User B's job.
        - Cluster converges toward fair-share equilibrium.
    """
    total_slots = 100
    pool = ResourceSlotPool(total_slots=total_slots)
    fs_tree = FairShareTree(root_id="cluster")
    # 50/50 entitlement between User A and User B
    fs_tree.add_node(FairShareNode(id="user_a", parent_id="cluster", shares=1.0))
    fs_tree.add_node(FairShareNode(id="user_b", parent_id="cluster", shares=1.0))

    preemption_policy = PreemptionPolicy(
        grace_period_seconds=30.0,
        starvation_deficit_threshold=0.4,
        preemption_bonus=5000.0,
    )
    scheduler = BatchSchedulerEngine(
        pool=pool,
        fairshare_tree=fs_tree,
        preemption_engine=ControlledPreemptionEngine(policy=preemption_policy),
    )

    t0 = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)
    t0_secs = t0.timestamp()

    # 1. User A fills all 100 slots
    running_jobs_a: list[JobSpec] = []
    for i in range(total_slots):
        job_a = JobSpec(
            id=f"job-a-{i:03d}",
            run_id="run-a",
            name=f"task-a-{i}",
            command="sleep 1000",
            user="user_a",
            checkpointable=(i % 2 == 0),
            created_at=t0 - timedelta(seconds=100),
        )
        pool.allocate(job_a)
        running_jobs_a.append(job_a)
        # Register staggered start times
        scheduler.record_job_start(job_a.id, t0_secs - float(i))

    assert pool.available_slots == 0
    assert pool.used_slots == 100

    # Record User A's historical usage (hogged cluster for 500 slot-seconds)
    fs_tree.record_usage("user_a", 500.0, timestamp=t0_secs)

    # 2. User B submits job-b-001 at t0
    job_b = JobSpec(
        id="job-b-001",
        run_id="run-b",
        name="task-b",
        command="compute",
        user="user_b",
        created_at=t0,
    )

    # 3. Schedule at t0 + 10s: User B has only waited 10s (< 30s grace period)
    # Decision: no preemption, job-b-001 remains pending
    decision_t10 = scheduler.schedule_cycle(
        pending_jobs=[job_b],
        running_jobs=running_jobs_a,
        current_timestamp=t0_secs + 10.0,
    )
    assert len(decision_t10.to_run) == 0
    assert len(decision_t10.preempted_jobs) == 0
    assert len(decision_t10.remains_pending) == 1
    assert decision_t10.remains_pending[0].id == "job-b-001"
    assert pool.used_slots == 100

    # 4. Schedule at t0 + 35s: User B has waited 35s (> 30s grace period)
    # Decision: Controlled preemption fires! User A's youngest checkpointable job is preempted.
    decision_t35 = scheduler.schedule_cycle(
        pending_jobs=[job_b],
        running_jobs=running_jobs_a,
        current_timestamp=t0_secs + 35.0,
    )

    # Preemption verified
    assert len(decision_t35.preempted_jobs) == 1
    preempted_id, reason = decision_t35.preempted_jobs[0]
    assert "user_a" in preempted_id or "job-a" in preempted_id
    assert "fair-share starvation" in reason

    # User B allocated to the freed slot!
    assert len(decision_t35.to_run) == 1
    assert decision_t35.to_run[0].id == "job-b-001"
    assert len(decision_t35.remains_pending) == 0

    # Conservation invariant holds: used_slots is still exactly 100 (99 from A + 1 from B)
    assert pool.used_slots == 100
    assert pool.is_allocated("job-b-001") is True
    assert pool.is_allocated(preempted_id) is False
