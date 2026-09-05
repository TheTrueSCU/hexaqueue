"""Directed Acyclic Graph (DAG) dependency models and evaluation engine.

Notes/Architectural Intent:
    Provides deterministic dependency graph validation, cycle detection
    (via Kahn's topological sort algorithm), trigger condition evaluation
    (AFTER_OK, AFTER_NOT_OK, AFTER_ANY, AFTER_CORR), and readiness checks
    for multi-stage job pipelines.
"""

from collections import defaultdict, deque
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.lifecycle import TerminalOutcome


class DependencyCycleError(HexaqueueError):
    """Exception raised when a cyclic dependency is detected in the job DAG."""


class TriggerCondition(StrEnum):
    """Trigger conditions dictating when a dependent child job becomes eligible to run.

    Conditions:
        AFTER_OK: Parent job must complete successfully (TerminalOutcome.COMPLETED).
        AFTER_NOT_OK: Parent job must finish with failure (TerminalOutcome.FAILED / TIMED_OUT).
        AFTER_ANY: Parent job reaches DONE regardless of outcome.
        AFTER_CORR: For array jobs, child task i runs after corresponding parent task i completes.
    """

    AFTER_OK = "AFTER_OK"
    AFTER_NOT_OK = "AFTER_NOT_OK"
    AFTER_ANY = "AFTER_ANY"
    AFTER_CORR = "AFTER_CORR"


class DependencySpec(BaseModel):
    """Specification of a dependency link between a child job and a parent job.

    Args:
        parent_job_id: ID of the upstream parent prerequisite job.
        condition: TriggerCondition required for this dependency to be satisfied.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_job_id: str = Field(description="Parent prerequisite job identifier")
    condition: TriggerCondition = Field(
        default=TriggerCondition.AFTER_OK, description="Prerequisite trigger condition"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate dependency link invariants."""
        if not self.parent_job_id.strip():
            msg = "parent_job_id cannot be empty"
            raise ValueError(msg)
        return self


def is_dependency_satisfied(
    condition: TriggerCondition,
    parent_outcome: TerminalOutcome | None,
) -> bool:
    """Evaluate whether a parent's terminal outcome satisfies the trigger condition.

    Args:
        condition: The TriggerCondition required by the child.
        parent_outcome: The parent's TerminalOutcome (or None if parent is not yet DONE).

    Returns:
        True if the parent outcome satisfies the condition, False otherwise.
    """
    if parent_outcome is None:
        return False

    match condition:
        case TriggerCondition.AFTER_OK:
            return parent_outcome == TerminalOutcome.COMPLETED
        case TriggerCondition.AFTER_NOT_OK:
            return parent_outcome in (TerminalOutcome.FAILED, TerminalOutcome.TIMED_OUT)
        case TriggerCondition.AFTER_ANY:
            return True
        case TriggerCondition.AFTER_CORR:
            return parent_outcome == TerminalOutcome.COMPLETED


class JobDagEngine:
    """Engine for validating, sorting, and evaluating job dependency graphs.

    Notes/Architectural Intent:
        Operates purely over job ID adjacency mappings to guarantee sub-millisecond
        cycle detection and dependency readiness evaluation.
    """

    def __init__(self, dependencies: dict[str, list[DependencySpec]] | None = None) -> None:
        """Initialize DAG engine with dependency mappings.

        Args:
            dependencies: Dictionary mapping child_job_id -> list of DependencySpec.
        """
        self._dependencies: dict[str, list[DependencySpec]] = defaultdict(list)
        if dependencies:
            for child_id, deps in dependencies.items():
                self._dependencies[child_id].extend(deps)

    def add_dependency(self, child_job_id: str, parent_job_id: str, condition: TriggerCondition = TriggerCondition.AFTER_OK) -> None:
        """Add a dependency link between child and parent.

        Args:
            child_job_id: The dependent downstream job ID.
            parent_job_id: The prerequisite upstream job ID.
            condition: The trigger condition.

        Raises:
            ValueError: If self-dependency is attempted (child_job_id == parent_job_id).
        """
        if child_job_id == parent_job_id:
            msg = f"Self-dependency detected: job '{child_job_id}' cannot depend on itself"
            raise ValueError(msg)

        self._dependencies[child_job_id].append(
            DependencySpec(parent_job_id=parent_job_id, condition=condition)
        )

    def validate_and_topological_sort(self, all_job_ids: set[str]) -> list[str]:
        """Validate that the dependency graph is acyclic and return a topological execution order.

        Uses Kahn's algorithm for O(V + E) deterministic cycle detection.

        Args:
            all_job_ids: Complete set of job IDs participating in the graph.

        Returns:
            List of job IDs ordered from upstream prerequisites to downstream dependents.

        Raises:
            DependencyCycleError: If a cyclic dependency is detected.
        """
        in_degree: dict[str, int] = {job_id: 0 for job_id in all_job_ids}
        adjacency: dict[str, list[str]] = defaultdict(list)

        # Build forward adjacency list: parent -> list of children
        for child_id, deps in self._dependencies.items():
            if child_id not in in_degree:
                in_degree[child_id] = 0
            for dep in deps:
                parent_id = dep.parent_job_id
                if parent_id not in in_degree:
                    in_degree[parent_id] = 0
                adjacency[parent_id].append(child_id)
                in_degree[child_id] += 1

        # Queue nodes with in-degree == 0 (no prerequisites)
        queue = deque(sorted([job_id for job_id, deg in in_degree.items() if deg == 0]))
        sorted_order: list[str] = []

        while queue:
            current = queue.popleft()
            sorted_order.append(current)

            for neighbor in adjacency[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(sorted_order) != len(in_degree):
            unresolved = [job_id for job_id, deg in in_degree.items() if deg > 0]
            msg = f"Cyclic dependency detected among jobs: {unresolved}"
            raise DependencyCycleError(msg)

        return sorted_order

    def is_job_ready(
        self,
        child_job_id: str,
        parent_outcomes: dict[str, TerminalOutcome | None],
    ) -> bool:
        """Check if all parent prerequisites for child_job_id are satisfied.

        Args:
            child_job_id: The job ID to evaluate.
            parent_outcomes: Dictionary mapping parent_job_id -> TerminalOutcome (or None if not done).

        Returns:
            True if all upstream dependencies are satisfied, False otherwise.
        """
        deps = self._dependencies.get(child_job_id, [])
        if not deps:
            return True

        for dep in deps:
            outcome = parent_outcomes.get(dep.parent_job_id)
            if not is_dependency_satisfied(dep.condition, outcome):
                return False

        return True


__all__ = [
    "DependencyCycleError",
    "DependencySpec",
    "JobDagEngine",
    "TriggerCondition",
    "is_dependency_satisfied",
]
