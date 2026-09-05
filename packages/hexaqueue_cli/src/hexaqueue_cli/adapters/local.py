"""In-process local client adapter for hq CLI.

Notes/Architectural Intent:
    Implements ClientPort by routing directly to in-process session controller
    and log stream port without network transport overhead.
"""

from hexaqueue_cli.domain.session import LocalCliSession, get_default_session
from hexaqueue_cli.ports.client import ClientPort
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission


class LocalClientAdapter(ClientPort):
    """In-process local client adapter."""

    def __init__(self, session: LocalCliSession | None = None) -> None:
        self._session = session or get_default_session()

    async def submit_run(self, submission: RunSubmission) -> RunStatusReport:
        """Submit a pipeline run to local in-process controller."""
        return await self._session.controller.submit_run(submission)

    async def get_run_status(self, run_id: str) -> RunStatusReport:
        """Get run status report from local in-process controller."""
        return await self._session.controller.get_run_status(run_id)

    async def get_job(self, job_id: str) -> JobSpec:
        """Get job metadata from local in-process controller."""
        return await self._session.controller.get_job(job_id)

    async def cancel_run(self, run_id: str) -> RunStatusReport:
        """Cancel run in local in-process controller."""
        return await self._session.controller.cancel_run(run_id)

    async def get_logs(self, job_id: str) -> list[LogChunk]:
        """Fetch captured logs from in-memory stream adapter."""
        return [
            c async for c in self._session.log_stream.stream_logs(job_id, follow=False)
        ]


__all__ = [
    "LocalClientAdapter",
]
