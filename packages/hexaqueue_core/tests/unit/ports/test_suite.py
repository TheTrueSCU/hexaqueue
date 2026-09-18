"""Unit tests for SuiteCompilerPort interface.

Notes/Architectural Intent:
    Verifies hexagonal boundary contract for hierarchical suite compilation,
    confirming ABC enforcement and method signature expectations.
"""

from typing import Any

import pytest

from hexaqueue_core.domain.dag import JobDagEngine
from hexaqueue_core.domain.group import ResourceOverrideSpec
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.suite import SuiteCompilationResult, SuiteSpec
from hexaqueue_core.ports.suite import SuiteCompilerPort


class DummySuiteCompiler(SuiteCompilerPort):
    """Concrete dummy implementation for testing port contract."""

    def compile(
        self,
        suite: SuiteSpec,
        run_id: str,
        global_env: dict[str, str] | None = None,
        global_tags: list[str] | None = None,
        global_resources: ResourceRequirements | ResourceOverrideSpec | None = None,
        global_variables: dict[str, Any] | None = None,
    ) -> SuiteCompilationResult:
        """Dummy implementation returning an empty compilation result."""
        dag = JobDagEngine()
        return SuiteCompilationResult(
            jobs=[],
            dependencies={},
            suite_task_map={suite.id: []},
            dag=dag,
        )


def test_suite_compiler_port_cannot_be_instantiated_directly() -> None:
    """Verifies that SuiteCompilerPort cannot be instantiated directly."""
    with pytest.raises(TypeError):
        SuiteCompilerPort()  # type: ignore[abstract]


def test_dummy_suite_compiler_satisfies_port() -> None:
    """Verifies that a subclass implementing compile satisfies the port contract."""
    compiler = DummySuiteCompiler()
    suite = SuiteSpec(id="test_suite")
    result = compiler.compile(suite=suite, run_id="run-123")

    count = result.job_count
    assert count == 0

    job = result.get_job("non-existent")
    assert job is None

    order = result.topological_order()
    assert order == []
