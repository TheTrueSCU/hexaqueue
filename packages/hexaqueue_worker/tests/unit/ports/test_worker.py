"""Tests for worker daemon port interface."""

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
