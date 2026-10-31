"""Unit tests for execution runtime port models and contracts."""

import inspect

import pytest

from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.ports.runtime import ExecutionRuntimePort, ProcessExecutionResult


def test_process_execution_result_valid():
    """Verify ProcessExecutionResult creation and invariants."""
    res = ProcessExecutionResult(
        exit_code=0,
        outcome=TerminalOutcome.COMPLETED,
        walltime_seconds=1.5,
    )
    assert res.exit_code == 0
    assert res.outcome == TerminalOutcome.COMPLETED
    assert res.walltime_seconds == 1.5


def test_process_execution_result_invalid_invariants():
    """Verify exit_code 0 must map to TerminalOutcome.COMPLETED."""
    with pytest.raises(
        ValueError, match="exit_code 0 must map to TerminalOutcome.COMPLETED"
    ):
        ProcessExecutionResult(
            exit_code=0,
            outcome=TerminalOutcome.FAILED,
            walltime_seconds=1.0,
        )


def test_execution_runtime_port_is_abstract() -> None:
    """Verify that ExecutionRuntimePort cannot be instantiated directly and is abstract."""
    is_abs = inspect.isabstract(ExecutionRuntimePort)
    assert is_abs is True
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        ExecutionRuntimePort()  # ty: ignore[call-non-callable] # type: ignore[abstract]


def test_execution_runtime_port_abstract_methods() -> None:
    """Verify abstract methods on ExecutionRuntimePort."""
    expected = {"execute", "terminate"}
    abstracts = ExecutionRuntimePort.__abstractmethods__
    diff = expected.difference(abstracts)
    assert len(diff) == 0
