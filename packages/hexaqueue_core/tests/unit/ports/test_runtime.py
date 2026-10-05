"""Unit tests for execution runtime port models and contracts."""

import pytest

from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.ports.runtime import ProcessExecutionResult


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
