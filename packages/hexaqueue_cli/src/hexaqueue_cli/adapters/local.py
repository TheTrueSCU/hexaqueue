"""Local and remote HTTP CQRS client adapter for the hq CLI.

Notes/Architectural Intent:
    Implements ClientPort by dispatching strongly typed Commands and Queries through
    Hexaqueue's unified CQRS ``ExecutionPipeline`` (backed either by the in-process
    ``LocalCliSession`` or by remote ``HttpSchedulerControllerAdapter`` and
    ``HttpCollateralServiceAdapter`` REST clients when a controller URL is configured).
"""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from pydantic import SecretStr

from hexaqueue_cli.domain.models import ClusterStatsReport
from hexaqueue_cli.domain.session import (
    LocalCliSession,
    get_default_session,
    resolve_controller_url,
)
from hexaqueue_cli.ports.client import ClientPort
from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralTier,
)
from hexaqueue_core.domain.cqrs import (
    CancelJobCommand,
    CancelRunCommand,
    CreateBastionSessionCommand,
    DeleteCollateralCommand,
    EvictExpiredCollateralCommand,
    ExplainJobQuery,
    GetCollateralBundleQuery,
    GetFairShareTreeQuery,
    GetJobLogDownloadUrlQuery,
    GetJobQuery,
    GetLogsQuery,
    GetNodesQuery,
    GetQueueStatsQuery,
    GetRunStatusQuery,
    HoldJobCommand,
    ListCollateralQuery,
    ListJobsQuery,
    ListRunsQuery,
    PinCollateralCommand,
    PresignedDownloadUrl,
    PromoteCollateralCommand,
    RegisterCollateralCommand,
    ReleaseJobCommand,
    SubmitRunCommand,
    SubmitSuiteCommand,
    UnpinCollateralCommand,
)
from hexaqueue_core.domain.exceptions import PermissionDeniedError
from hexaqueue_core.domain.explainability import (
    FairShareTreeReport,
    SchedulingDecisionReport,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.redaction import MultiTenantRedactionFilter
from hexaqueue_core.domain.suite import SuiteSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.adapters.http import (
    HttpCollateralServiceAdapter,
    HttpSchedulerControllerAdapter,
)
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline
from hexaqueue_worker.domain.pty import PtySessionInfo, PtySessionRequest
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


class LocalClientAdapter(ClientPort):
    """CQRS-backed CLI client adapter supporting in-process and remote controller execution.

    Args:
        session: Explicit in-process ``LocalCliSession`` override (forces local mode
            unless ``controller_url`` is also specified).
        controller_url: Explicit remote ``hexaqueue-server`` base URL. When omitted
            and ``session`` is ``None``, resolves via ``resolve_controller_url()``.
        admin_token: Optional administrative bearer token override (defaults to
            ``HEXAQUEUE_ADMIN_TOKEN`` environment variable in remote mode).
        transport: Optional custom ``httpx.AsyncBaseTransport`` for hermetic testing.

    Notes/Architectural Intent:
        Unifies local developer runs and distributed operator commands under a single
        ``ClientPort`` adapter so RBAC, redaction, and CQRS contracts remain identical
        across local and remote targets without starting local workers in remote mode.
    """

    def __init__(
        self,
        session: LocalCliSession | None = None,
        *,
        controller_url: str | None = None,
        admin_token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        resolved_url = (
            resolve_controller_url(controller_url)
            if controller_url is not None or session is None
            else None
        )
        self._controller_url = resolved_url
        self._is_remote = resolved_url is not None

        if resolved_url is not None:
            raw_token = admin_token or os.environ.get("HEXAQUEUE_ADMIN_TOKEN") or None
            secret = SecretStr(raw_token) if raw_token else None
            self._session: LocalCliSession | None = None
            self._remote_controller: HttpSchedulerControllerAdapter | None = (
                HttpSchedulerControllerAdapter(
                    base_url=resolved_url,
                    admin_token=secret,
                    user_id="default",
                    elevate=False,
                    transport=transport,
                )
            )
            self._remote_collateral: HttpCollateralServiceAdapter | None = (
                HttpCollateralServiceAdapter(
                    base_url=resolved_url,
                    admin_token=secret,
                    user_id="default",
                    elevate=False,
                    transport=transport,
                )
            )
            self._pipeline: Any = create_hexaqueue_execution_pipeline(
                controller=self._remote_controller,
                collateral_service=self._remote_collateral,
            )
        else:
            local_session = session or get_default_session()
            self._session = local_session
            self._remote_controller = None
            self._remote_collateral = None
            self._pipeline = local_session.pipeline

    def _require_session(self) -> LocalCliSession:
        """Return active in-process LocalCliSession or raise when in remote mode."""
        if self._session is None:
            msg = "In-process LocalCliSession is unavailable in remote controller mode."
            raise RuntimeError(msg)
        return self._session

    def _require_remote_controller(self) -> HttpSchedulerControllerAdapter:
        """Return active HTTP controller adapter or raise when in local mode."""
        if self._remote_controller is None:
            msg = "Remote controller adapter is unavailable in local mode."
            raise RuntimeError(msg)
        return self._remote_controller

    def _require_remote_collateral(self) -> HttpCollateralServiceAdapter:
        """Return active HTTP collateral adapter or raise when in local mode."""
        if self._remote_collateral is None:
            msg = "Remote collateral adapter is unavailable in local mode."
            raise RuntimeError(msg)
        return self._remote_collateral

    async def _execute_async(
        self,
        message: Any,
        *,
        user_id: str = "default",
        elevate: bool = False,
    ) -> Any:
        """Execute a CQRS command or query with remote caller identity binding."""
        with ExitStack() as stack:
            if self._remote_controller is not None:
                stack.enter_context(self._remote_controller.acting_as(user_id, elevate))
            if self._remote_collateral is not None:
                stack.enter_context(self._remote_collateral.acting_as(user_id, elevate))
            return await self._pipeline.execute_async(message)

    async def submit_run(
        self,
        submission: RunSubmission,
        user_id: str = "default",
        elevate: bool = False,
    ) -> RunStatusReport:
        """Submit a DAG pipeline run through the CQRS execution pipeline."""
        cmd = SubmitRunCommand(
            run_spec=submission.run_spec,
            jobs=submission.jobs,
            dependencies=submission.dependencies,
            user_id=user_id,
            elevate=elevate,
        )
        res: RunStatusReport = await self._execute_async(
            cmd, user_id=user_id, elevate=elevate
        )
        return res

    async def submit_suite(
        self,
        suite: SuiteSpec,
        user_id: str = "default",
        elevate: bool = False,
    ) -> RunStatusReport:
        """Compile and submit a hierarchical suite pipeline run."""
        if self._is_remote:
            ctrl = self._require_remote_controller()
            with ctrl.acting_as(user_id, elevate):
                return await ctrl.submit_suite(suite)

        cmd = SubmitSuiteCommand(suite_spec=suite, user_id=user_id, elevate=elevate)
        res: RunStatusReport = await self._execute_async(
            cmd, user_id=user_id, elevate=elevate
        )
        return res

    async def get_run_status(
        self,
        run_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> RunStatusReport:
        """Retrieve aggregate status for a pipeline run."""
        if self._is_remote:
            ctrl = self._require_remote_controller()
            with ctrl.acting_as(user_id, elevate):
                return await ctrl.get_run_status(run_id)

        qry = GetRunStatusQuery(run_id=run_id, user_id=user_id, elevate=elevate)
        res: RunStatusReport = await self._execute_async(
            qry, user_id=user_id, elevate=elevate
        )
        return res

    async def get_job(
        self,
        job_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> JobSpec:
        """Retrieve metadata and status for an individual job."""
        qry = GetJobQuery(job_id=job_id, user_id=user_id, elevate=elevate)
        res: JobSpec = await self._execute_async(qry, user_id=user_id, elevate=elevate)
        return res

    async def list_jobs(
        self,
        run_id: str | None = None,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[JobSpec]:
        """List registered jobs across runs or filtered by run identifier."""
        qry = ListJobsQuery(run_id=run_id, user_id=user_id, elevate=elevate)
        res: list[JobSpec] = await self._execute_async(
            qry, user_id=user_id, elevate=elevate
        )
        return res

    async def list_runs(
        self,
        limit: int = 100,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[RunStatusReport]:
        """List registered pipeline runs visible to the caller."""
        if self._is_remote:
            ctrl = self._require_remote_controller()
            with ctrl.acting_as(user_id, elevate):
                return await ctrl.list_runs(limit=limit)

        qry = ListRunsQuery(limit=limit, user_id=user_id, elevate=elevate)
        res: list[RunStatusReport] = await self._execute_async(
            qry, user_id=user_id, elevate=elevate
        )
        return res

    async def cancel_run(
        self, run_id: str, user_id: str = "default", elevate: bool = False
    ) -> RunStatusReport:
        """Cancel an active pipeline run via CQRS."""
        cmd = CancelRunCommand(run_id=run_id, user_id=user_id, elevate=elevate)
        res: RunStatusReport = await self._execute_async(
            cmd, user_id=user_id, elevate=elevate
        )
        return res

    async def cancel_job(
        self, job_id: str, user_id: str = "default", elevate: bool = False
    ) -> JobSpec:
        """Cancel an individual job via CQRS."""
        cmd = CancelJobCommand(job_id=job_id, user_id=user_id, elevate=elevate)
        res: JobSpec = await self._execute_async(cmd, user_id=user_id, elevate=elevate)
        return res

    async def hold_job(
        self, job_id: str, user_id: str = "default", elevate: bool = False
    ) -> JobSpec:
        """Place an administrative hold on a job via CQRS."""
        cmd = HoldJobCommand(job_id=job_id, user_id=user_id, elevate=elevate)
        res: JobSpec = await self._execute_async(cmd, user_id=user_id, elevate=elevate)
        return res

    async def release_job(
        self, job_id: str, user_id: str = "default", elevate: bool = False
    ) -> JobSpec:
        """Release an administrative hold on a job via CQRS."""
        cmd = ReleaseJobCommand(job_id=job_id, user_id=user_id, elevate=elevate)
        res: JobSpec = await self._execute_async(cmd, user_id=user_id, elevate=elevate)
        return res

    async def get_logs(
        self,
        job_id: str,
        tail: int | None = None,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[LogChunk]:
        """Fetch historical execution logs for a job."""
        if self._is_remote:
            qry = GetLogsQuery(
                job_id=job_id, tail=tail, user_id=user_id, elevate=elevate
            )
            res: list[LogChunk] = await self._execute_async(
                qry, user_id=user_id, elevate=elevate
            )
            return res

        session = self._require_session()
        return [
            chunk
            async for chunk in session.log_stream.stream_logs(
                job_id, follow=False, tail=tail
            )
        ]

    async def get_log_download_url(
        self,
        job_id: str,
        expires_in_seconds: int = 900,
        user_id: str = "default",
        elevate: bool = False,
    ) -> str:
        """Retrieve presigned direct download URL for job execution logs."""
        if self._is_remote:
            ctrl = self._require_remote_controller()
            with ctrl.acting_as(user_id, elevate):
                return await ctrl.get_job_log_download_url(
                    job_id, expires_in_seconds=expires_in_seconds
                )

        qry = GetJobLogDownloadUrlQuery(
            job_id=job_id,
            expires_in_seconds=expires_in_seconds,
            user_id=user_id,
            elevate=elevate,
        )
        res: PresignedDownloadUrl = await self._execute_async(
            qry, user_id=user_id, elevate=elevate
        )
        return res.download_url

    async def stream_logs(
        self, job_id: str, follow: bool = False, tail: int | None = None
    ) -> AsyncIterator[LogChunk]:
        """Stream logs for a job with optional real-time tail follow."""
        if not self._is_remote:
            session = self._require_session()
            async for chunk in session.log_stream.stream_logs(
                job_id, follow=follow, tail=tail
            ):
                yield chunk
            return

        seen_offsets: set[int] = set()
        initial = await self.get_logs(job_id, tail=tail)
        for chunk in initial:
            seen_offsets.add(chunk.offset)
            yield chunk

        while follow:
            await asyncio.sleep(0.5)
            latest = await self.get_logs(job_id)
            for chunk in latest:
                if chunk.offset not in seen_offsets:
                    seen_offsets.add(chunk.offset)
                    yield chunk

    async def get_cluster_stats(
        self, user_id: str = "default", elevate: bool = False
    ) -> ClusterStatsReport:
        """Retrieve high-level cluster state and backlog statistics."""
        qry = GetQueueStatsQuery(user_id=user_id, elevate=elevate)
        report: ClusterStatsReport = await self._execute_async(
            qry, user_id=user_id, elevate=elevate
        )
        if not self._is_remote and report.active_workers == 0:
            session = self._require_session()
            if getattr(session.worker, "_running", False):
                report = report.model_copy(update={"active_workers": 1})
        return report

    async def get_nodes(
        self, user_id: str = "default", elevate: bool = False
    ) -> list[NodeTelemetryPulse]:
        """Retrieve telemetry pulses for registered compute worker nodes.

        Notes/Architectural Intent:
            Dispatches ``GetNodesQuery`` via the CQRS pipeline. In local mode without
            explicitly registered nodes, collects the in-process worker pulse as a
            developer fallback. In remote mode, never fabricates synthetic local nodes.
        """
        qry = GetNodesQuery(user_id=user_id, elevate=elevate)
        pulses: list[NodeTelemetryPulse] = await self._execute_async(
            qry, user_id=user_id, elevate=elevate
        )
        if pulses or self._is_remote:
            return pulses

        session = self._require_session()
        worker = session.worker
        active_jobs = len(getattr(worker, "_active_jobs", set()))
        worker_id = getattr(worker._config, "worker_id", "local-worker")
        return [
            session.telemetry.collect_pulse(
                worker_id=worker_id, active_jobs=active_jobs
            )
        ]

    async def create_pty_session(
        self, request: PtySessionRequest, job_owner: str = "default"
    ) -> PtySessionInfo:
        """Create an interactive terminal PTY session inside a running job."""
        if self._is_remote:
            ctrl = self._require_remote_controller()
            elevated = "operator" in request.roles or "admin" in request.roles
            with ctrl.acting_as(request.user_id, elevated):
                return await ctrl.create_pty_session(request)

        session = self._require_session()
        return await session.pty.create_session(request, job_owner=job_owner)

    async def explain_job(
        self,
        job_id: str,
        requesting_user: str = "default",
        is_admin: bool = False,
    ) -> SchedulingDecisionReport:
        """Generate or fetch redacted explainability report for a job."""
        if self._is_remote:
            ctrl = self._require_remote_controller()
            with ctrl.acting_as(requesting_user, is_admin):
                return await ctrl.explain_job(job_id)

        qry = ExplainJobQuery(
            job_id=job_id,
            requesting_user=requesting_user,
            is_admin=is_admin,
        )
        res: SchedulingDecisionReport = await self._execute_async(
            qry, user_id=requesting_user, elevate=is_admin
        )
        return res

    async def get_fairshare_tree(
        self,
        requesting_user: str = "default",
        is_admin: bool = False,
    ) -> FairShareTreeReport:
        """Retrieve hierarchical fair-share tree report with multi-tenant redaction."""
        if self._is_remote:
            ctrl = self._require_remote_controller()
            with ctrl.acting_as(requesting_user, is_admin):
                report = await ctrl.get_fairshare_tree()
        else:
            qry = GetFairShareTreeQuery(
                requesting_user=requesting_user,
                is_admin=is_admin,
            )
            report = await self._execute_async(
                qry, user_id=requesting_user, elevate=is_admin
            )
        redaction = MultiTenantRedactionFilter()
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
        ttl_seconds: int | None = None,
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        """Register and stage a collateral bundle into CAS storage."""
        if target_path and (
            ".." in name or "/" in name or "\\" in name or Path(name).is_absolute()
        ):
            msg = f"Collateral name '{name}' contains illegal path components."
            raise ValueError(msg)

        checksum = (
            checksum_sha256 if len(checksum_sha256) == 64 else checksum_sha256.zfill(64)
        )

        if self._is_remote and target_path and Path(target_path).is_file():
            content = Path(target_path).read_bytes()
            ctrl = self._require_remote_controller()
            coll = self._require_remote_collateral()
            with ctrl.acting_as(user_id, elevate), coll.acting_as(user_id, elevate):
                bundle = await coll.stage_stream(
                    name, content, sha256_checksum=checksum
                )
            if (
                tier == CollateralTier.PERMANENT
                and bundle.tier != CollateralTier.PERMANENT
                and elevate
            ):
                bundle = await self.promote_collateral(
                    bundle.id, user_id=user_id, elevate=elevate
                )
            return bundle

        cmd = RegisterCollateralCommand(
            name=name,
            size_bytes=max(1, size_bytes),
            checksum_sha256=checksum,
            tier=tier,
            kind=kind,
            target_path=target_path,
            ttl_seconds=ttl_seconds,
            user_id=user_id,
            elevate=elevate,
        )
        registered: CollateralBundle = await self._execute_async(
            cmd, user_id=user_id, elevate=elevate
        )
        if not self._is_remote and target_path and Path(target_path).is_file():
            session = self._require_session()
            if session.collateral_service is not None:
                await session.collateral_service.stage_file(
                    registered.id, Path(target_path)
                )
                return await session.collateral_service.process_quarantine(
                    registered.id
                )
        return registered

    async def list_collateral(
        self,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[CollateralBundle]:
        """List collateral bundles visible to the requesting user."""
        qry = ListCollateralQuery(user_id=user_id, elevate=elevate)
        res: list[CollateralBundle] = await self._execute_async(
            qry, user_id=user_id, elevate=elevate
        )
        return res

    async def get_collateral(
        self,
        collateral_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        """Retrieve metadata for a single collateral bundle."""
        qry = GetCollateralBundleQuery(
            collateral_id=collateral_id, user_id=user_id, elevate=elevate
        )
        bundle: CollateralBundle = await self._execute_async(
            qry, user_id=user_id, elevate=elevate
        )
        if not elevate and bundle.owner != user_id:
            msg = (
                f"Collateral {collateral_id} belongs to another owner; "
                "explicit administrative elevation (--admin / elevate=true) is required."
            )
            raise PermissionDeniedError(msg)
        return bundle

    async def promote_collateral(
        self,
        collateral_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        """Promote a TEMPORARY collateral bundle to PERMANENT tier."""
        cmd = PromoteCollateralCommand(
            collateral_id=collateral_id, user_id=user_id, elevate=elevate
        )
        res: CollateralBundle = await self._execute_async(
            cmd, user_id=user_id, elevate=elevate
        )
        return res

    async def pin_collateral(
        self,
        collateral_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        """Pin a collateral bundle against eviction."""
        cmd = PinCollateralCommand(
            collateral_id=collateral_id, user_id=user_id, elevate=elevate
        )
        res: CollateralBundle = await self._execute_async(
            cmd, user_id=user_id, elevate=elevate
        )
        return res

    async def unpin_collateral(
        self,
        collateral_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> CollateralBundle:
        """Unpin a collateral bundle to permit garbage collection eligibility."""
        cmd = UnpinCollateralCommand(
            collateral_id=collateral_id, user_id=user_id, elevate=elevate
        )
        res: CollateralBundle = await self._execute_async(
            cmd, user_id=user_id, elevate=elevate
        )
        return res

    async def delete_collateral(
        self,
        collateral_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> str:
        """Delete an unused collateral bundle from CAS storage."""
        cmd = DeleteCollateralCommand(
            collateral_id=collateral_id, user_id=user_id, elevate=elevate
        )
        res: str = await self._execute_async(cmd, user_id=user_id, elevate=elevate)
        return res

    async def evict_expired_collateral(
        self,
        max_age_seconds: int | None = None,
        high_watermark_bytes: int | None = None,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[str]:
        """Trigger garbage collection eviction for expired temporary collateral."""
        cmd = EvictExpiredCollateralCommand(
            max_age_seconds=max_age_seconds,
            high_watermark_bytes=high_watermark_bytes,
            user_id=user_id,
            elevate=elevate,
        )
        res: list[str] = await self._execute_async(
            cmd, user_id=user_id, elevate=elevate
        )
        return res

    async def create_bastion_session(
        self,
        node_id: str,
        session_id: str = "",
        user_id: str = "default",
        elevate: bool = False,
    ) -> PtySessionInfo:
        """Create administrative bastion session (requires elevation)."""
        resolved_session_id = session_id or f"bastion-{uuid4().hex[:8]}"
        cmd = CreateBastionSessionCommand(
            node_id=node_id,
            session_id=resolved_session_id,
            user_id=user_id,
            elevate=elevate,
        )
        if self._is_remote:
            if not cmd.elevate:
                msg = (
                    f"Permission denied: Bastion shell access on node '{node_id}' "
                    "requires explicit administrative elevation (--admin)."
                )
                raise PermissionDeniedError(msg)
            ctrl = self._require_remote_controller()
            with ctrl.acting_as(user_id, elevate):
                return await ctrl.create_bastion_session(node_id)

        res: PtySessionInfo = await self._execute_async(
            cmd, user_id=user_id, elevate=elevate
        )
        return res


__all__ = [
    "LocalClientAdapter",
]
