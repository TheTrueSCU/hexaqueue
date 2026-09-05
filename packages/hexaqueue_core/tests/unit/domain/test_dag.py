"""Unit tests for DAG engine, cycle detection, and trigger conditions."""

import pytest

from hexaqueue_core.domain.dag import (
    DependencyCycleError,
    DependencySpec,
    JobDagEngine,
    TriggerCondition,
    is_dependency_satisfied,
)
from hexaqueue_core.domain.lifecycle import TerminalOutcome


def test_dependency_spec_validation():
    """Verify DependencySpec requires non-empty parent_job_id."""
    dep = DependencySpec(parent_job_id="parent-1", condition=TriggerCondition.AFTER_OK)
    assert dep.parent_job_id == "parent-1"
    assert dep.condition == TriggerCondition.AFTER_OK

    with pytest.raises(ValueError, match="parent_job_id cannot be empty"):
        DependencySpec(parent_job_id="   ")


def test_is_dependency_satisfied():
    """Verify trigger condition evaluation against parent terminal outcomes."""
    # Parent not yet terminal (None)
    assert not is_dependency_satisfied(TriggerCondition.AFTER_OK, None)
    assert not is_dependency_satisfied(TriggerCondition.AFTER_NOT_OK, None)
    assert not is_dependency_satisfied(TriggerCondition.AFTER_ANY, None)

    # AFTER_OK
    assert is_dependency_satisfied(
        TriggerCondition.AFTER_OK, TerminalOutcome.COMPLETED
    )
    assert not is_dependency_satisfied(
        TriggerCondition.AFTER_OK, TerminalOutcome.FAILED
    )
    assert not is_dependency_satisfied(
        TriggerCondition.AFTER_OK, TerminalOutcome.TIMED_OUT
    )
    assert not is_dependency_satisfied(
        TriggerCondition.AFTER_OK, TerminalOutcome.CANCELLED
    )

    # AFTER_NOT_OK
    assert not is_dependency_satisfied(
        TriggerCondition.AFTER_NOT_OK, TerminalOutcome.COMPLETED
    )
    assert is_dependency_satisfied(
        TriggerCondition.AFTER_NOT_OK, TerminalOutcome.FAILED
    )
    assert is_dependency_satisfied(
        TriggerCondition.AFTER_NOT_OK, TerminalOutcome.TIMED_OUT
    )
    assert not is_dependency_satisfied(
        TriggerCondition.AFTER_NOT_OK, TerminalOutcome.CANCELLED
    )

    # AFTER_ANY
    assert is_dependency_satisfied(
        TriggerCondition.AFTER_ANY, TerminalOutcome.COMPLETED
    )
    assert is_dependency_satisfied(TriggerCondition.AFTER_ANY, TerminalOutcome.FAILED)
    assert is_dependency_satisfied(
        TriggerCondition.AFTER_ANY, TerminalOutcome.TIMED_OUT
    )
    assert is_dependency_satisfied(
        TriggerCondition.AFTER_ANY, TerminalOutcome.CANCELLED
    )

    # AFTER_CORR
    assert is_dependency_satisfied(
        TriggerCondition.AFTER_CORR, TerminalOutcome.COMPLETED
    )
    assert not is_dependency_satisfied(
        TriggerCondition.AFTER_CORR, TerminalOutcome.FAILED
    )


def test_dag_linear_pipeline():
    """Verify topological sort of a linear pipeline: A -> B -> C."""
    dag = JobDagEngine()
    dag.add_dependency("B", "A", TriggerCondition.AFTER_OK)
    dag.add_dependency("C", "B", TriggerCondition.AFTER_OK)

    sorted_jobs = dag.validate_and_topological_sort({"A", "B", "C"})
    assert sorted_jobs == ["A", "B", "C"]


def test_dag_diamond_pipeline():
    """Verify diamond pipeline: A -> B, A -> C, B -> D, C -> D."""
    dag = JobDagEngine()
    dag.add_dependency("B", "A")
    dag.add_dependency("C", "A")
    dag.add_dependency("D", "B")
    dag.add_dependency("D", "C")

    sorted_jobs = dag.validate_and_topological_sort({"A", "B", "C", "D"})
    assert sorted_jobs[0] == "A"
    assert set(sorted_jobs[1:3]) == {"B", "C"}
    assert sorted_jobs[3] == "D"


def test_dag_self_dependency():
    """Verify that adding a self-dependency raises ValueError immediately."""
    dag = JobDagEngine()
    with pytest.raises(ValueError, match="Self-dependency detected"):
        dag.add_dependency("A", "A")


def test_dag_cycle_detection():
    """Verify that circular dependencies raise DependencyCycleError."""
    dag = JobDagEngine()
    dag.add_dependency("B", "A")
    dag.add_dependency("C", "B")
    dag.add_dependency("A", "C")

    with pytest.raises(DependencyCycleError, match="Cyclic dependency detected"):
        dag.validate_and_topological_sort({"A", "B", "C"})


def test_dag_is_job_ready():
    """Verify readiness check for a job with multiple prerequisite dependencies."""
    dag = JobDagEngine()
    dag.add_dependency("child", "parent1", TriggerCondition.AFTER_OK)
    dag.add_dependency("child", "parent2", TriggerCondition.AFTER_NOT_OK)

    # No parent outcomes yet
    assert not dag.is_job_ready("child", {})

    # Only parent1 complete
    assert not dag.is_job_ready(
        "child", {"parent1": TerminalOutcome.COMPLETED, "parent2": None}
    )

    # parent1 complete and parent2 failed (meets AFTER_NOT_OK)
    assert dag.is_job_ready(
        "child",
        {
            "parent1": TerminalOutcome.COMPLETED,
            "parent2": TerminalOutcome.FAILED,
        },
    )

    # Independent job with no dependencies is always ready
    assert dag.is_job_ready("independent", {})
