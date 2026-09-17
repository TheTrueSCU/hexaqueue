"""Unit tests for SchedulerExplainabilityPort ABC."""

import pytest

from hexaqueue_core.domain.explainability import (
    FairShareNodeReport,
    FairShareTreeReport,
    PriorityBreakdown,
    SchedulingDecisionReport,
)
from hexaqueue_core.domain.lifecycle import JobState
from hexaqueue_core.ports.explainability import SchedulerExplainabilityPort


class DummyExplainabilityAdapter(SchedulerExplainabilityPort):
    """Reference dummy adapter implementing SchedulerExplainabilityPort."""

    def explain_job(
        self,
        job_id: str,
        requesting_user: str,
        is_admin: bool = False,
    ) -> SchedulingDecisionReport:
        breakdown = PriorityBreakdown(
            base_score=10.0,
            age_score=20.0,
            fairshare_score=30.0,
            preemption_bonus=0.0,
            total_priority=60.0,
            age_seconds=10.0,
            fairshare_factor=1.0,
            target_share=1.0,
            actual_usage=0.0,
        )
        return SchedulingDecisionReport(
            job_id=job_id,
            user=requesting_user,
            state=JobState.PENDING,
            queue_position=1,
            queue_total=1,
            priority_breakdown=breakdown,
            summary="Dummy ready",
        )

    def explain_fairshare(
        self,
        requesting_user: str,
        is_admin: bool = False,
    ) -> FairShareTreeReport:
        node = FairShareNodeReport(
            id="root",
            shares=1.0,
            target_share=1.0,
            raw_usage=0.0,
            decayed_usage=0.0,
            fairshare_factor=1.0,
            children=[],
        )
        return FairShareTreeReport(
            root=node,
            half_life_seconds=86400.0,
            total_decayed_usage=0.0,
        )


def test_scheduler_explainability_port_contract() -> None:
    """Verify dummy adapter satisfies SchedulerExplainabilityPort interface."""
    adapter = DummyExplainabilityAdapter()
    res_is_instance = isinstance(adapter, SchedulerExplainabilityPort)
    assert res_is_instance is True

    report = adapter.explain_job("job-1", "user-1")
    res_id = report.job_id
    assert res_id == "job-1"

    tree = adapter.explain_fairshare("user-1")
    res_root = tree.root.id
    assert res_root == "root"


def test_cannot_instantiate_abstract_port() -> None:
    """Verify ABC prevents direct instantiation."""
    with pytest.raises(TypeError):
        SchedulerExplainabilityPort()  # type: ignore[abstract]
