"""In-process local client adapter for hq CLI.

Notes/Architectural Intent:
    Implements ClientPort by routing directly to in-process session controller
    and log stream port without network transport overhead.
"""

from __future__ import annotations

from hexaqueue_cli.domain.session import LocalCliSession, get_default_session
from hexaqueue_cli.ports.client import ClientPort
from hexaqueue_core.domain.explainability import (
    FairShareTreeReport,
    SchedulingDecisionReport,
)
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

    async def explain_job(
        self,
        job_id: str,
        requesting_user: str = "default",
        is_admin: bool = False,
    ) -> SchedulingDecisionReport:
        """Generate explainability report for a job in the local session."""
        from datetime import UTC, datetime

        from hexaqueue_core.domain.explainability import SchedulerExplainabilityEngine
        from hexaqueue_core.domain.redaction import MultiTenantRedactionFilter
        from hexaqueue_core.domain.scheduling import ResourceSlotPool

        engine = SchedulerExplainabilityEngine()
        redaction = MultiTenantRedactionFilter()
        all_jobs = await self._session.controller.list_jobs()
        pool = ResourceSlotPool(total_slots=4)
        report = engine.explain_job(
            job_id=job_id,
            all_jobs=all_jobs,
            pool=pool,
            current_timestamp=datetime.now(UTC).timestamp(),
        )
        return redaction.redact_decision_report(
            report, requesting_user=requesting_user, is_admin=is_admin
        )

    async def get_fairshare_tree(
        self,
        requesting_user: str = "default",
        is_admin: bool = False,
    ) -> FairShareTreeReport:
        """Generate fair-share tree report for the local session."""
        from datetime import UTC, datetime

        from hexaqueue_core.domain.explainability import (
            SchedulerExplainabilityEngine,
        )
        from hexaqueue_core.domain.redaction import MultiTenantRedactionFilter

        engine = SchedulerExplainabilityEngine()
        redaction = MultiTenantRedactionFilter()
        report = engine.explain_fairshare(datetime.now(UTC).timestamp())
        return redaction.redact_fairshare_tree(
            report, requesting_user=requesting_user, is_admin=is_admin
        )


__all__ = [
    "LocalClientAdapter",
]
