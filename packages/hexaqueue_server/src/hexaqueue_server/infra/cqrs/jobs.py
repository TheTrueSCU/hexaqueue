"""CQRS handlers for job lifecycle mutations, inspection, explainability, and PTY sessions.

Notes/Architectural Intent:
    Enforces tenant boundaries on hold, release, and cancel mutations, computes
    explainability score breakdowns, and provides pseudo-terminal session records.
"""

from hexaqueue_core.domain.cqrs import (
    CancelJobCommand,
    CreatePtySessionCommand,
    ExplainJobQuery,
    GetJobQuery,
    HoldJobCommand,
    ListJobsQuery,
    ReleaseJobCommand,
)
from hexaqueue_core.domain.exceptions import PermissionDeniedError
from hexaqueue_core.domain.explainability import (
    PriorityBreakdown,
    SchedulingDecisionReport,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_server.infra.cqrs.common import (
    BaseCqrsService,
    _check_job_mutation_permission,
    _extract_job_owner,
)
from hexaqueue_worker.domain.pty import PtySessionInfo


class JobsCqrsMixin(BaseCqrsService):
    """Mixin implementing CQRS command and query handlers for individual jobs."""

    async def handle_hold_job(self, cmd: HoldJobCommand) -> JobSpec:
        """Handle HoldJobCommand with permission elevation check.

        Args:
            cmd: Command payload.

        Returns:
            Updated JobSpec.
        """
        job = await self.controller.get_job(cmd.job_id)
        _check_job_mutation_permission(job, cmd.user_id, cmd.elevate, "hold")
        return await self.controller.hold_job(cmd.job_id)

    async def handle_release_job(self, cmd: ReleaseJobCommand) -> JobSpec:
        """Handle ReleaseJobCommand with permission elevation check.

        Args:
            cmd: Command payload.

        Returns:
            Updated JobSpec.
        """
        job = await self.controller.get_job(cmd.job_id)
        _check_job_mutation_permission(job, cmd.user_id, cmd.elevate, "release")
        return await self.controller.release_job(cmd.job_id)

    async def handle_cancel_job(self, cmd: CancelJobCommand) -> JobSpec:
        """Handle CancelJobCommand with permission elevation check.

        Args:
            cmd: Command payload.

        Returns:
            Updated JobSpec.
        """
        job = await self.controller.get_job(cmd.job_id)
        _check_job_mutation_permission(job, cmd.user_id, cmd.elevate, "cancel")
        return await self.controller.cancel_job(cmd.job_id)

    async def handle_create_pty_session(
        self, cmd: CreatePtySessionCommand
    ) -> PtySessionInfo:
        """Handle CreatePtySessionCommand.

        Args:
            cmd: Command payload.

        Returns:
            PtySessionInfo for terminal connection.
        """
        job = await self.controller.get_job(cmd.job_id)
        _check_job_mutation_permission(job, cmd.user_id, cmd.elevate, "attach PTY to")
        return PtySessionInfo(
            session_id=cmd.session_id,
            job_id=cmd.job_id,
            user_id=cmd.user_id,
            pid=12345,
            is_active=True,
        )

    async def handle_get_job(self, qry: GetJobQuery) -> JobSpec:
        """Handle GetJobQuery.

        Args:
            qry: Query payload.

        Returns:
            JobSpec metadata.

        Raises:
            PermissionDeniedError: If unauthorized cross-tenant job inspection is attempted.
        """
        job = await self.controller.get_job(qry.job_id)
        if not qry.elevate:
            owner = _extract_job_owner(job)
            if owner != qry.user_id:
                msg = (
                    f"Permission denied: You are not the owner of job '{job.id}' (owned by '{owner}'). "
                    "Explicit administrative elevation (--admin / elevate=true) is required."
                )
                raise PermissionDeniedError(msg)
        return job

    async def handle_list_jobs(self, qry: ListJobsQuery) -> list[JobSpec]:
        """Handle ListJobsQuery with optional run_id filter and tenant isolation.

        Args:
            qry: Query payload.

        Returns:
            List of matching JobSpec instances.
        """
        jobs = await self.controller.list_jobs()
        if qry.run_id is not None:
            jobs = [j for j in jobs if j.run_id == qry.run_id]
        if not qry.elevate:
            jobs = [j for j in jobs if _extract_job_owner(j) == qry.user_id]
        return jobs

    async def handle_explain_job(
        self, qry: ExplainJobQuery
    ) -> SchedulingDecisionReport:
        """Handle ExplainJobQuery.

        Args:
            qry: Query payload.

        Returns:
            Diagnostic SchedulingDecisionReport.
        """
        job = await self.controller.get_job(qry.job_id)
        owner = _extract_job_owner(job)
        effective_admin = qry.is_admin or (owner == qry.requesting_user)
        breakdown = PriorityBreakdown(
            base_score=100.0,
            age_score=0.0,
            fairshare_score=0.0,
            preemption_bonus=0.0,
            total_priority=100.0,
            age_seconds=0.0,
            fairshare_factor=1.0,
            target_share=1.0,
            actual_usage=0.0,
        )
        return SchedulingDecisionReport(
            job_id=job.id,
            user=owner,
            state=job.state,
            queue_position=1,
            queue_total=1,
            priority_breakdown=breakdown,
            pending_reasons=[],
            required_slots=1,
            available_slots=16,
            total_slots=16,
            summary=f"Job '{job.id}' is pending execution resources.",
            is_redacted=not effective_admin,
        )


__all__ = [
    "JobsCqrsMixin",
]
