"""Hexagonal port interface for hierarchical suite and matrix compilers.

Notes/Architectural Intent:
    Defines the contract for recursively resolving hierarchical suite bundles,
    applying cascading context overrides, expanding combinatorial parameter matrices,
    and producing topologically sorted JobSpec batches with DAG dependencies.
"""

from abc import ABC, abstractmethod
from typing import Any

from hexaqueue_core.domain.group import ResourceOverrideSpec
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.suite import SuiteCompilationResult, SuiteSpec


class SuiteCompilerPort(ABC):
    """Abstract port interface for hierarchical suite compilers."""

    @abstractmethod
    def compile(
        self,
        suite: SuiteSpec,
        run_id: str,
        global_env: dict[str, str] | None = None,
        global_tags: list[str] | None = None,
        global_resources: ResourceRequirements | ResourceOverrideSpec | None = None,
        global_variables: dict[str, Any] | None = None,
    ) -> SuiteCompilationResult:
        """Compile a hierarchical SuiteSpec into a concrete SuiteCompilationResult.

        Args:
            suite: Root hierarchical suite specification.
            run_id: Root run identifier to associate with generated jobs.
            global_env: Optional global environment variables.
            global_tags: Optional global placement tags.
            global_resources: Optional global resource defaults or overrides.
            global_variables: Optional global template variables.

        Returns:
            Fully resolved SuiteCompilationResult containing flattened jobs and DAG.

        Raises:
            SuiteCompilationError: If duplicate job IDs, invalid dependencies, or cycles exist.
            VariableInterpolationError: If unmapped template variables are encountered.
        """
        raise NotImplementedError


__all__ = [
    "SuiteCompilerPort",
]
