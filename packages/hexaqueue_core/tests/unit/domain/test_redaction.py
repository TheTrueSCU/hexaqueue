"""Unit tests for MultiTenantRedactionFilter."""

from hexaqueue_core.domain.explainability import (
    FairShareNodeReport,
    FairShareTreeReport,
    PendingReason,
    PendingReasonCode,
    PriorityBreakdown,
    SchedulingDecisionReport,
)
from hexaqueue_core.domain.lifecycle import JobState
from hexaqueue_core.domain.redaction import MultiTenantRedactionFilter


def _create_sample_report() -> SchedulingDecisionReport:
    """Helper creating a sample unredacted SchedulingDecisionReport."""
    breakdown = PriorityBreakdown(
        base_score=100.0,
        age_score=50.0,
        fairshare_score=200.0,
        preemption_bonus=0.0,
        total_priority=350.0,
        age_seconds=300.0,
        fairshare_factor=0.85,
        target_share=0.5,
        actual_usage=1200.0,
    )
    reasons = [
        PendingReason(
            code=PendingReasonCode.BLOCKED_BY_PRIORITY_ANCHOR,
            message="Blocked by anchor job 'job-secret-999' from user 'alice-cui'.",
            details={"anchor_id": "job-secret-999", "anchor_user": "alice-cui"},
        )
    ]
    return SchedulingDecisionReport(
        job_id="job-target-1",
        user="alice-cui",
        state=JobState.PENDING,
        queue_position=2,
        queue_total=5,
        priority_breakdown=breakdown,
        pending_reasons=reasons,
        blocking_anchor_id="job-secret-999",
        required_slots=2,
        available_slots=1,
        total_slots=8,
        estimated_wait_seconds=60.0,
        summary="Rank #2 of 5: Blocked by job-secret-999 (alice-cui)",
        is_redacted=False,
    )


def test_redaction_self_access_unmodified() -> None:
    """Verify job owner receives unredacted report."""
    filter_ = MultiTenantRedactionFilter()
    report = _create_sample_report()
    result = filter_.redact_decision_report(
        report=report, requesting_user="alice-cui", is_admin=False
    )

    res_user = result.user
    assert res_user == "alice-cui"
    res_anchor = result.blocking_anchor_id
    assert res_anchor == "job-secret-999"
    res_redacted = result.is_redacted
    assert res_redacted is False
    res_usage = result.priority_breakdown.actual_usage
    assert res_usage == 1200.0


def test_redaction_admin_access_unmodified() -> None:
    """Verify administrator receives unredacted report regardless of username."""
    filter_ = MultiTenantRedactionFilter()
    report = _create_sample_report()
    result = filter_.redact_decision_report(
        report=report, requesting_user="sysadmin", is_admin=True
    )

    res_user = result.user
    assert res_user == "alice-cui"
    res_redacted = result.is_redacted
    assert res_redacted is False


def test_redaction_cross_tenant_sanitization() -> None:
    """Verify external tenant receives pseudonymized and sanitized report."""
    filter_ = MultiTenantRedactionFilter()
    report = _create_sample_report()
    result = filter_.redact_decision_report(
        report=report, requesting_user="bob-tenant", is_admin=False
    )

    res_redacted = result.is_redacted
    assert res_redacted is True
    res_user = result.user
    assert res_user.startswith("tenant_user_")
    assert "alice" not in res_user

    res_anchor = result.blocking_anchor_id
    assert res_anchor is not None
    assert res_anchor.startswith("job_")
    assert "secret" not in res_anchor

    # Check that reasons and summary stripped sensitive terms
    res_summary = result.summary
    assert "job-secret-999" not in res_summary
    assert "alice-cui" not in res_summary

    res_reasons = result.pending_reasons
    assert len(res_reasons) == 1
    assert "job-secret-999" not in res_reasons[0].message
    assert "alice-cui" not in res_reasons[0].message

    # Actual usage is masked to 0.0
    res_usage = result.priority_breakdown.actual_usage
    assert res_usage == 0.0


def test_redaction_fairshare_tree() -> None:
    """Verify cross-tenant fair-share tree anonymizes other users' nodes."""
    filter_ = MultiTenantRedactionFilter()
    child_alice = FairShareNodeReport(
        id="alice",
        parent_id="root",
        shares=1.0,
        target_share=0.5,
        raw_usage=100.0,
        decayed_usage=90.0,
        fairshare_factor=0.8,
        children=[],
    )
    child_bob = FairShareNodeReport(
        id="bob",
        parent_id="root",
        shares=1.0,
        target_share=0.5,
        raw_usage=50.0,
        decayed_usage=45.0,
        fairshare_factor=0.9,
        children=[],
    )
    root_node = FairShareNodeReport(
        id="root",
        shares=2.0,
        target_share=1.0,
        raw_usage=150.0,
        decayed_usage=135.0,
        fairshare_factor=1.0,
        children=[child_alice, child_bob],
    )
    tree_report = FairShareTreeReport(
        root=root_node, half_life_seconds=86400.0, total_decayed_usage=135.0
    )

    # Bob requests tree
    sanitized = filter_.redact_fairshare_tree(
        tree_report, requesting_user="bob", is_admin=False
    )

    # Bob's own node remains visible with usage
    bob_node = next((c for c in sanitized.root.children if c.id == "bob"), None)
    assert bob_node is not None
    res_bob_usage = bob_node.raw_usage
    assert res_bob_usage == 50.0

    # Alice's node is pseudonymized and usage zeroed
    alice_node = next((c for c in sanitized.root.children if c.id != "bob"), None)
    assert alice_node is not None
    assert alice_node.id.startswith("tenant_user_")
    res_alice_usage = alice_node.raw_usage
    assert res_alice_usage == 0.0
