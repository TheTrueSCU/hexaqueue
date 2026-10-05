"""Unit tests for scheduler explainability engine and decision reporting."""

from datetime import UTC, datetime, timedelta

import pytest

from hexaqueue_core.domain.explainability import (
    PendingReasonCode,
    SchedulerExplainabilityEngine,
)
from hexaqueue_core.domain.fairshare import FairShareNode, FairShareTree
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, JobStatus
from hexaqueue_core.domain.priority import JobPriorityCalculator, PriorityWeights
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.scheduling import ResourceSlotPool


def test_explainability_job_not_found() -> None:
    """Verify ValueError is raised if target job is missing."""
    engine = SchedulerExplainabilityEngine()
    pool = ResourceSlotPool(total_slots=4)
    with pytest.raises(ValueError, match="Job with id 'missing-1' not found"):
        engine.explain_job(
            job_id="missing-1",
            all_jobs=[],
            pool=pool,
            current_timestamp=1000.0,
        )


def test_explainability_ready_job() -> None:
    """Verify explain_job for job at top of queue with available slots."""
    pool = ResourceSlotPool(total_slots=4)
    j1 = JobSpec(
        id="job-1",
        run_id="run-1",
        name="test-task",
        command="echo hello",
        user="alice",
        resources=ResourceRequirements(cpus=2),
        created_at=datetime.now(UTC) - timedelta(seconds=120),
    )
    engine = SchedulerExplainabilityEngine()
    report = engine.explain_job(
        job_id="job-1",
        all_jobs=[j1],
        pool=pool,
        current_timestamp=datetime.now(UTC).timestamp(),
    )

    res_pos = report.queue_position
    assert res_pos == 1
    res_tot = report.queue_total
    assert res_tot == 1
    res_reasons = report.pending_reasons
    assert len(res_reasons) == 1
    res_code = res_reasons[0].code
    assert res_code == PendingReasonCode.READY
    res_summary = report.summary
    assert "ready for immediate dispatch" in res_summary


def test_explainability_blocked_by_anchor_and_saturation() -> None:
    """Verify rank #2 job receives BLOCKED_BY_PRIORITY_ANCHOR and CLUSTER_SATURATED."""
    pool = ResourceSlotPool(total_slots=4)
    # Fill 3 of 4 slots with a running job
    j_running = JobSpec(
        id="job-run",
        run_id="run-1",
        name="running",
        command="sleep 100",
        user="system",
        resources=ResourceRequirements(cpus=3),
        status=JobStatus(state=JobState.RUNNING),
    )
    pool.allocate(j_running)

    # j_anchor: higher priority, needs 2 cpus
    j_anchor = JobSpec(
        id="job-anchor",
        run_id="run-1",
        name="anchor",
        command="run",
        user="alice",
        priority=200,
        resources=ResourceRequirements(cpus=2),
        created_at=datetime.now(UTC) - timedelta(seconds=100),
    )
    # j_target: lower priority, needs 2 cpus
    j_target = JobSpec(
        id="job-target",
        run_id="run-1",
        name="target",
        command="run",
        user="bob",
        priority=50,
        resources=ResourceRequirements(cpus=2),
        created_at=datetime.now(UTC) - timedelta(seconds=50),
    )

    engine = SchedulerExplainabilityEngine()
    now_ts = datetime.now(UTC).timestamp()
    report = engine.explain_job(
        job_id="job-target",
        all_jobs=[j_running, j_anchor, j_target],
        pool=pool,
        current_timestamp=now_ts,
    )

    res_pos = report.queue_position
    assert res_pos == 2
    res_tot = report.queue_total
    assert res_tot == 2
    res_anchor_id = report.blocking_anchor_id
    assert res_anchor_id == "job-anchor"

    reason_codes = {r.code for r in report.pending_reasons}
    assert PendingReasonCode.BLOCKED_BY_PRIORITY_ANCHOR in reason_codes
    assert PendingReasonCode.CLUSTER_SATURATED in reason_codes

    # Priority breakdown checks
    breakdown = report.priority_breakdown
    res_base = breakdown.base_score
    assert res_base == 500.0  # 10.0 * 50
    res_total_p = breakdown.total_priority
    assert res_total_p > res_base


def test_explainability_fairshare_throttle_and_insufficient_capacity() -> None:
    """Verify FAIRSHARE_THROTTLE and INSUFFICIENT_CLUSTER_CAPACITY blocker detection."""
    pool = ResourceSlotPool(total_slots=4)
    tree = FairShareTree()
    tree.add_node(FairShareNode(id="charlie", parent_id="root", shares=1.0))
    tree.add_node(FairShareNode(id="dana", parent_id="root", shares=1.0))
    now_ts = 1000.0
    tree.record_usage("charlie", 10000.0, now_ts)

    j_oversized = JobSpec(
        id="job-huge",
        run_id="run-1",
        name="oversized",
        command="run",
        user="charlie",
        resources=ResourceRequirements(cpus=8),  # Exceeds total capacity 4
        created_at=datetime.now(UTC) - timedelta(seconds=10),
    )

    engine = SchedulerExplainabilityEngine(fairshare_tree=tree)
    report = engine.explain_job(
        job_id="job-huge",
        all_jobs=[j_oversized],
        pool=pool,
        current_timestamp=now_ts,
    )

    reason_codes = {r.code for r in report.pending_reasons}
    assert PendingReasonCode.INSUFFICIENT_CLUSTER_CAPACITY in reason_codes
    assert PendingReasonCode.FAIRSHARE_THROTTLE in reason_codes
    res_req = report.required_slots
    assert res_req == 8
    res_tot_slots = report.total_slots
    assert res_tot_slots == 4


def test_explain_fairshare_tree_report() -> None:
    """Verify hierarchical fair-share tree diagnostic report generation."""
    tree = FairShareTree(half_life_seconds=86400.0)
    tree.add_node(FairShareNode(id="engineering", parent_id="root", shares=2.0))
    tree.add_node(FairShareNode(id="alice", parent_id="engineering", shares=1.0))
    tree.add_node(FairShareNode(id="bob", parent_id="engineering", shares=1.0))
    tree.record_usage("alice", 300.0, 1000.0)
    tree.record_usage("bob", 200.0, 1000.0)

    calc = JobPriorityCalculator(PriorityWeights())
    engine = SchedulerExplainabilityEngine(
        priority_calculator=calc, fairshare_tree=tree
    )

    now_ts = 1000.0
    tree_report = engine.explain_fairshare(current_timestamp=now_ts)

    res_root_id = tree_report.root.id
    assert res_root_id == "root"
    res_half_life = tree_report.half_life_seconds
    assert res_half_life == 86400.0

    eng_node = next(
        (c for c in tree_report.root.children if c.id == "engineering"), None
    )
    assert eng_node is not None
    res_eng_shares = eng_node.shares
    assert res_eng_shares == 2.0
    res_child_count = len(eng_node.children)
    assert res_child_count == 2
