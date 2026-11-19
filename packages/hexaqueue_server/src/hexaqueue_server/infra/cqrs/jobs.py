"""CQRS handlers for job lifecycle mutations, inspection, explainability, and PTY sessions.

Notes/Architectural Intent:
    Enforces tenant boundaries on hold, release, and cancel mutations, computes
    explainability score breakdowns, and provides pseudo-terminal session records.
"""

import time

from hexaqueue_core.domain.cqrs import (
    CancelJobCommand,
    CreatePtySessionCommand,
    ExplainJobQuery,
    GetJobQuery,
    HoldJobCommand,
    ListJobsQuery,
    ReleaseJobCommand,
    SimulatePlacementQuery,
)
from hexaqueue_core.domain.exceptions import PermissionDeniedError
from hexaqueue_core.domain.explainability import (
    SchedulerExplainabilityEngine,
    SchedulingDecisionReport,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.redaction import MultiTenantRedactionFilter
from hexaqueue_core.domain.scheduling import ResourceSlotPool
from hexaqueue_server.domain.memento import PlacementSimulationReport
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
        """Handle ExplainJobQuery using SchedulerExplainabilityEngine and redaction.

        Args:
            qry: Query payload.

        Returns:
            Diagnostic SchedulingDecisionReport.
        """
        all_jobs = await self.controller.list_jobs()
        nodes = await self.controller.list_nodes()
        total_cpus = sum(n.capacity.total_cpus for n in nodes if n.capacity is not None)
        coord = getattr(self.controller, "_lease_coordinator", None)
        if coord is not None and hasattr(coord, "list_active_workers"):
            seen = {n.node_id for n in nodes}
            for reg, _, _ in coord.list_active_workers():
                if reg.worker_id not in seen:
                    total_cpus += reg.ocpus

        total_slots = max(1, total_cpus) if total_cpus > 0 else 16
        pool = ResourceSlotPool(total_slots=total_slots, total_cpus=total_slots)
        engine = SchedulerExplainabilityEngine()
        report = engine.explain_job(
            job_id=qry.job_id,
            all_jobs=all_jobs,
            pool=pool,
            current_timestamp=time.time(),
        )
        redaction = MultiTenantRedactionFilter()
        return redaction.redact_decision_report(
            report, requesting_user=qry.requesting_user, is_admin=qry.is_admin
        )

    async def handle_simulate_placement(
        self, qry: SimulatePlacementQuery
    ) -> PlacementSimulationReport:
        """Handle SimulatePlacementQuery by evaluating dry-run placement without state changes.

        Args:
            qry: Query payload containing candidate jobs.

        Returns:
            PlacementSimulationReport with hypothetical placement outcomes.
        """
        return await self.controller.simulate_placement(
            candidate_jobs=qry.candidate_jobs,
            collateral_hash_map=qry.collateral_hash_map,
        )


__all__ = [
    "JobsCqrsMixin",
]
