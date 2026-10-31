"""Tests for worker daemon port interface."""

import inspect

import pytest

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.ports.runtime import ProcessExecutionResult
from hexaqueue_worker.domain.models import WorkerMetrics
from hexaqueue_worker.ports.worker import WorkerDaemonPort


class DummyWorkerDaemon(WorkerDaemonPort):
    """Concrete implementation of WorkerDaemonPort for interface testing."""

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def execute_job(self, job: JobSpec) -> ProcessExecutionResult:
        return ProcessExecutionResult(
            exit_code=0,
            outcome=TerminalOutcome.COMPLETED,
            walltime_seconds=0.1,
        )

    async def get_metrics(self) -> WorkerMetrics:
        return WorkerMetrics(worker_id="dummy", active_jobs=0, is_running=False)


def test_worker_port_instantiation() -> None:
    """Verify concrete subclass can be instantiated."""
    worker = DummyWorkerDaemon()
    assert isinstance(worker, WorkerDaemonPort)


def test_worker_daemon_port_is_abstract() -> None:
    """Verify that WorkerDaemonPort cannot be instantiated directly and is abstract."""
    is_abs = inspect.isabstract(WorkerDaemonPort)
    assert is_abs is True
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        WorkerDaemonPort()  # ty: ignore[call-non-callable] # type: ignore[abstract]


def test_worker_daemon_port_abstract_methods() -> None:
    """Verify abstract methods on WorkerDaemonPort."""
    expected = {"execute_job", "get_metrics", "start", "stop"}
    abstracts = WorkerDaemonPort.__abstractmethods__
    diff = expected.difference(abstracts)
    assert len(diff) == 0
