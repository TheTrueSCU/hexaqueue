"""In-process local client adapter for hq CLI.

Notes/Architectural Intent:
    Implements ClientPort by routing directly to in-process session controller
    and log stream port without network transport overhead.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

from hexaqueue_cli.domain.models import ClusterStatsReport
from hexaqueue_cli.domain.session import LocalCliSession, get_default_session
from hexaqueue_cli.ports.client import ClientPort
from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralState,
    CollateralTier,
)
from hexaqueue_core.domain.exceptions import PermissionDeniedError
from hexaqueue_core.domain.explainability import (
    FairShareTreeReport,
    SchedulingDecisionReport,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.domain.suite import SuiteCompiler, SuiteSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission
from hexaqueue_worker.domain.pty import PtySessionInfo, PtySessionRequest
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


def _extract_job_owner(job: JobSpec) -> str:
    """Extract owner tag or env from job specification."""
    for tag in job.tags:
        if tag.startswith("owner:"):
            return tag.split(":", 1)[1]
    return job.env.get("HEXAQUEUE_OWNER", "default")


def _check_job_mutation_permission(
    job: JobSpec, user_id: str, elevate: bool, action_name: str
) -> None:
    """Verify that caller has permission to mutate the job."""
    owner = _extract_job_owner(job)
    if owner != "default" and owner != user_id and not elevate:
        msg = (
            f"Permission denied: You are not the owner of job '{job.id}' (owned by '{owner}'). "
            f"To {action_name} this job, explicit administrative elevation (--admin / elevate=true) is required."
        )
        raise PermissionDeniedError(msg)


class LocalClientAdapter(ClientPort):
    """In-process local client adapter."""

    def __init__(self, session: LocalCliSession | None = None) -> None:
        self._session = session or get_default_session()

    async def submit_run(self, submission: RunSubmission) -> RunStatusReport:
        """Submit a pipeline run to local in-process controller."""
        return await self._session.controller.submit_run(submission)

    async def submit_suite(
        self,
        suite: SuiteSpec,
        user_id: str = "default",
        elevate: bool = False,
    ) -> RunStatusReport:
        """Submit a hierarchical suite pipeline run to local controller."""
        compiler = SuiteCompiler()
        result = compiler.compile(suite, run_id=suite.id)
        run_spec = RunSpec(
            id=suite.id,
            name=suite.name or suite.id,
            tags=[f"owner:{user_id}"],
        )
        dependencies = {
            child_id: [dep.parent_job_id for dep in deps]
            for child_id, deps in result.dependencies.items()
        }
        submission = RunSubmission(
            run_spec=run_spec,
            jobs=result.jobs,
            dependencies=dependencies,
        )
        return await self._session.controller.submit_run(submission)

    async def get_run_status(self, run_id: str) -> RunStatusReport:
        """Get run status report from local in-process controller."""
        return await self._session.controller.get_run_status(run_id)

    async def get_job(self, job_id: str) -> JobSpec:
        """Get job metadata from local in-process controller."""
        return await self._session.controller.get_job(job_id)

    async def list_jobs(self) -> list[JobSpec]:
        """List all registered jobs across runs."""
        return await self._session.controller.list_jobs()

    async def cancel_run(
        self, run_id: str, user_id: str = "default", elevate: bool = False
    ) -> RunStatusReport:
        """Cancel run in local in-process controller."""
        if not elevate and user_id != "default":
            jobs = await self._session.controller.list_jobs()
            run_jobs = [j for j in jobs if j.run_id == run_id]
            for j in run_jobs:
                _check_job_mutation_permission(j, user_id, elevate, "cancel run")
        return await self._session.controller.cancel_run(run_id)

    async def cancel_job(
        self, job_id: str, user_id: str = "default", elevate: bool = False
    ) -> JobSpec:
        """Cancel an individual job."""
        job = await self._session.controller.get_job(job_id)
        _check_job_mutation_permission(job, user_id, elevate, "cancel")
        return await self._session.controller.cancel_job(job_id)

    async def hold_job(
        self, job_id: str, user_id: str = "default", elevate: bool = False
    ) -> JobSpec:
        """Place an administrative hold on a job."""
        job = await self._session.controller.get_job(job_id)
        _check_job_mutation_permission(job, user_id, elevate, "hold")
        return await self._session.controller.hold_job(job_id)

    async def release_job(
        self, job_id: str, user_id: str = "default", elevate: bool = False
    ) -> JobSpec:
        """Release an administrative hold on a job."""
        job = await self._session.controller.get_job(job_id)
        _check_job_mutation_permission(job, user_id, elevate, "release")
        return await self._session.controller.release_job(job_id)

    async def get_logs(self, job_id: str) -> list[LogChunk]:
        """Fetch captured logs from in-memory stream adapter."""
        return [
            c async for c in self._session.log_stream.stream_logs(job_id, follow=False)
        ]

    async def stream_logs(
        self, job_id: str, follow: bool = False, tail: int | None = None
    ) -> AsyncIterator[LogChunk]:
        """Stream logs for a job with optional real-time tail follow."""
        async for chunk in self._session.log_stream.stream_logs(
            job_id, follow=follow, tail=tail
        ):
            yield chunk

    async def get_cluster_stats(self) -> ClusterStatsReport:
        """Retrieve high-level cluster state and backlog statistics."""
        from hexaqueue_core.domain.lifecycle import JobState

        all_jobs = await self._session.controller.list_jobs()
        running_cnt = sum(1 for j in all_jobs if j.state == JobState.RUNNING)
        pending_cnt = sum(1 for j in all_jobs if j.state == JobState.PENDING)
        blocked_cnt = sum(1 for j in all_jobs if j.state == JobState.BLOCKED)
        completed_cnt = sum(
            1
            for j in all_jobs
            if j.state == JobState.DONE and str(j.outcome) == "COMPLETED"
        )
        failed_cnt = sum(
            1
            for j in all_jobs
            if j.state == JobState.DONE and str(j.outcome) != "COMPLETED"
        )

        total_runs = len(getattr(self._session.controller, "_runs", {}))
        active_workers = 1 if getattr(self._session.worker, "_running", False) else 0

        return ClusterStatsReport(
            total_runs=total_runs,
            total_jobs=len(all_jobs),
            running_jobs=running_cnt,
            pending_jobs=pending_cnt,
            blocked_jobs=blocked_cnt,
            completed_jobs=completed_cnt,
            failed_jobs=failed_cnt,
            active_workers=active_workers,
        )

    async def get_nodes(self) -> list[NodeTelemetryPulse]:
        """Retrieve telemetry pulses for registered compute worker nodes."""
        worker = self._session.worker
        active_jobs = len(getattr(worker, "_active_jobs", set()))
        worker_id = getattr(worker._config, "worker_id", "local-worker")
        pulse = self._session.telemetry.collect_pulse(
            worker_id=worker_id, active_jobs=active_jobs
        )
        return [pulse]

    async def create_pty_session(
        self, request: PtySessionRequest, job_owner: str = "default"
    ) -> PtySessionInfo:
        """Create an interactive terminal PTY session inside a running job."""
        return await self._session.pty.create_session(request, job_owner=job_owner)

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

    async def register_collateral(
        self,
        name: str,
        size_bytes: int,
        checksum_sha256: str,
        tier: CollateralTier = CollateralTier.TEMPORARY,
        kind: CollateralKind = CollateralKind.BUNDLE,
        target_path: str = "",
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        """Register and stage a collateral bundle."""
        checksum = (
            checksum_sha256 if len(checksum_sha256) == 64 else checksum_sha256.zfill(64)
        )
        return CollateralBundle(
            id=f"col-{uuid4().hex[:8]}",
            job_id="global",
            filename=name,
            size_bytes=size_bytes,
            sha256_checksum=checksum,
            tier=tier,
            kind=kind,
            state=CollateralState.REGISTERED,
            staging_uri=f"s3://staging/collateral/{name}",
        )

    async def create_bastion_session(
        self,
        node_id: str,
        session_id: str = "",
        user_id: str = "default",
        elevate: bool = False,
    ) -> PtySessionInfo:
        """Create administrative bastion session (requires elevation)."""
        if not elevate:
            msg = (
                f"Permission denied: Bastion shell access on node '{node_id}' "
                "requires explicit administrative elevation (--admin)."
            )
            raise PermissionDeniedError(msg)
        return PtySessionInfo(
            session_id=session_id or f"bastion-{uuid4().hex[:8]}",
            job_id=f"bastion-{node_id}",
            user_id=user_id,
            pid=99999,
            is_active=True,
        )


__all__ = [
    "LocalClientAdapter",
]
