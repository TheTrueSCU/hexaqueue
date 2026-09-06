"""Tests for ClientPort interface."""

from datetime import UTC, datetime

from hexaqueue_cli.ports.client import ClientPort
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import RunState
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission


class DummyClient(ClientPort):
    """Concrete implementation for ClientPort tests."""

    async def submit_run(self, submission: RunSubmission) -> RunStatusReport:
        return RunStatusReport(
            run_id=submission.run_spec.id,
            state=RunState.SUBMITTED,
            total_jobs=1,
            completed_jobs=0,
            failed_jobs=0,
            running_jobs=0,
            pending_jobs=1,
            created_at=datetime.now(UTC),
        )

    async def get_run_status(self, run_id: str) -> RunStatusReport:
        return RunStatusReport(
            run_id=run_id,
            state=RunState.DONE,
            total_jobs=1,
            completed_jobs=1,
            failed_jobs=0,
            running_jobs=0,
            pending_jobs=0,
            created_at=datetime.now(UTC),
        )

    async def get_job(self, job_id: str) -> JobSpec:
        return JobSpec(id=job_id, run_id="r1", name="j1", command="echo 1")

    async def cancel_run(self, run_id: str) -> RunStatusReport:
        return RunStatusReport(
            run_id=run_id,
            state=RunState.DONE,
            total_jobs=1,
            completed_jobs=0,
            failed_jobs=0,
            running_jobs=0,
            pending_jobs=0,
            created_at=datetime.now(UTC),
        )

    async def get_logs(self, job_id: str) -> list[LogChunk]:
        return [LogChunk(job_id=job_id, content="hello", offset=0)]


def test_client_port_instantiation() -> None:
    """Verify concrete subclass can be instantiated."""
    client = DummyClient()
    assert isinstance(client, ClientPort)
