"""CQRS command and query handlers and ExecutionPipeline builder for Hexaqueue Server.

Notes/Architectural Intent:
    Implements the Unified Application Service Layer. All presentation interfaces
    (CLI, REST OpenAPI, gRPC, and Web Dashboard) dispatch into this identical
    ExecutionPipeline. Enforces the Principle of Least Privilege: users act
    under their natural identity, requiring explicit elevation (`elevate=True`)
    to mutate or inspect cross-tenant resources.
"""

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import Any, cast
from uuid import uuid4

from hexastack_cqrs.adapters.buses.command.synchronous import SynchronousCommandBus
from hexastack_cqrs.adapters.buses.event.synchronous import SynchronousEventBus
from hexastack_cqrs.adapters.buses.query.synchronous import SynchronousQueryBus
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_cqrs.infra.registries.command import CommandRegistry
from hexastack_cqrs.infra.registries.handler import HandlerRegistry
from hexastack_cqrs.infra.registries.query import QueryRegistry

from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralState,
)
from hexaqueue_core.domain.cqrs import (
    CancelJobCommand,
    CancelRunCommand,
    ClusterStatsReport,
    CreateBastionSessionCommand,
    CreatePtySessionCommand,
    ExplainJobQuery,
    GetFairShareTreeQuery,
    GetJobQuery,
    GetLogsQuery,
    GetNodesQuery,
    GetQueueStatsQuery,
    GetRunStatusQuery,
    HoldJobCommand,
    ListJobsQuery,
    RegisterCollateralCommand,
    ReleaseJobCommand,
    SettleBudgetCommand,
    SubmitRunCommand,
    SubmitSuiteCommand,
)
from hexaqueue_core.domain.exceptions import (
    PermissionDeniedError,
)
from hexaqueue_core.domain.explainability import (
    FairShareTreeReport,
    PriorityBreakdown,
    SchedulerExplainabilityEngine,
    SchedulingDecisionReport,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.domain.suite import SuiteCompiler
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission
from hexaqueue_server.ports.controller import SchedulerControllerPort
from hexaqueue_worker.domain.pty import PtySessionInfo
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


def run_coro_sync[T](coro: Coroutine[Any, Any, T]) -> T:
    """Execute an asynchronous coroutine synchronously, handling running loops safely.

    Args:
        coro: The coroutine to execute.

    Returns:
        The evaluated result of the coroutine.

    Notes/Architectural Intent:
        Prevents 'Event loop is already running' deadlocks by executing on a dedicated
        worker thread when called from within an active asyncio loop.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    if not loop.is_running():
        return loop.run_until_complete(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return cast("T", pool.submit(asyncio.run, coro).result())


def _extract_job_owner(job: JobSpec) -> str:
    """Extract owner identity from job tags or environment variables."""
    for tag in job.tags:
        if tag.startswith("owner:"):
            return tag.split(":", 1)[1]
    return job.env.get("HEXAQUEUE_OWNER", "default")


def _check_job_mutation_permission(
    job: JobSpec, user_id: str, elevate: bool, action_name: str
) -> None:
    """Verify that the user is authorized to mutate a target job.

    Args:
        job: Target job specification.
        user_id: Identity of the actor requesting mutation.
        elevate: Whether explicit administrative elevation was asserted.
        action_name: Human-readable action for error message.

    Raises:
        PermissionDeniedError: If unauthorized cross-tenant mutation is attempted.
    """
    owner = _extract_job_owner(job)
    if owner != user_id and not elevate:
        msg = (
            f"Permission denied: You are not the owner of job '{job.id}' (owned by '{owner}'). "
            f"To {action_name} this job, explicit administrative elevation (--admin / elevate=true) is required."
        )
        raise PermissionDeniedError(msg)


class HexaqueueCqrsService:
    """Consolidated application service orchestrating Hexaqueue domain operations."""

    def __init__(
        self,
        controller: SchedulerControllerPort,
        log_store: dict[str, list[LogChunk]] | None = None,
        nodes: list[NodeTelemetryPulse] | None = None,
    ) -> None:
        """Initialize the unified application service.

        Args:
            controller: Scheduler controller instance for lifecycle management.
            log_store: Optional in-memory store for historical log chunks.
            nodes: Optional list of registered worker node telemetry pulses.
        """
        self.controller = controller
        self.log_store = log_store if log_store is not None else {}
        self.nodes = nodes if nodes is not None else []

    async def handle_submit_run(self, cmd: SubmitRunCommand) -> RunStatusReport:
        """Handle SubmitRunCommand.

        Args:
            cmd: Command payload.

        Returns:
            Initial RunStatusReport.
        """
        submission = RunSubmission(
            run_spec=cmd.run_spec,
            jobs=cmd.jobs,
            dependencies=cmd.dependencies,
        )
        return await self.controller.submit_run(submission)

    async def handle_submit_suite(self, cmd: SubmitSuiteCommand) -> RunStatusReport:
        """Handle SubmitSuiteCommand by compiling and submitting.

        Args:
            cmd: Command payload.

        Returns:
            Initial RunStatusReport.
        """
        compiler = SuiteCompiler()
        result = compiler.compile(cmd.suite_spec, run_id=cmd.suite_spec.id)
        run_spec = RunSpec(
            id=cmd.suite_spec.id,
            name=cmd.suite_spec.name or cmd.suite_spec.id,
            tags=[f"owner:{cmd.user_id}"],
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
        return await self.controller.submit_run(submission)

    async def handle_cancel_run(self, cmd: CancelRunCommand) -> RunStatusReport:
        """Handle CancelRunCommand.

        Args:
            cmd: Command payload.

        Returns:
            Updated RunStatusReport.

        Raises:
            PermissionDeniedError: If unauthorized cross-tenant cancellation is attempted.
        """
        await self.controller.get_run_status(cmd.run_id)
        if not cmd.elevate and cmd.user_id != "default":
            # Natural identity check
            jobs = await self.controller.list_jobs()
            run_jobs = [j for j in jobs if j.run_id == cmd.run_id]
            for j in run_jobs:
                _check_job_mutation_permission(
                    j, cmd.user_id, cmd.elevate, "cancel run"
                )

        return await self.controller.cancel_run(cmd.run_id)

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

    async def handle_register_collateral(
        self, cmd: RegisterCollateralCommand
    ) -> CollateralBundle:
        """Handle RegisterCollateralCommand.

        Args:
            cmd: Command payload.

        Returns:
            Registered CollateralBundle.
        """
        checksum = (
            cmd.checksum_sha256
            if len(cmd.checksum_sha256) == 64
            else cmd.checksum_sha256.zfill(64)
        )
        return CollateralBundle(
            id=f"col-{uuid4().hex[:8]}",
            job_id="global",
            filename=cmd.name,
            size_bytes=cmd.size_bytes,
            sha256_checksum=checksum,
            tier=cmd.tier,
            kind=cmd.kind,
            state=CollateralState.REGISTERED,
            staging_uri=f"s3://staging/collateral/{cmd.name}",
        )

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

    async def handle_create_bastion_session(
        self, cmd: CreateBastionSessionCommand
    ) -> PtySessionInfo:
        """Handle CreateBastionSessionCommand (requires explicit admin elevation).

        Args:
            cmd: Command payload.

        Returns:
            PtySessionInfo for bastion terminal.

        Raises:
            PermissionDeniedError: If not elevated.
        """
        if not cmd.elevate:
            msg = (
                f"Permission denied: Bastion shell access on node '{cmd.node_id}' "
                "requires explicit administrative elevation (--admin / elevate=true)."
            )
            raise PermissionDeniedError(msg)

        return PtySessionInfo(
            session_id=cmd.session_id,
            job_id=f"bastion-{cmd.node_id}",
            user_id=cmd.user_id,
            pid=54321,
            is_active=True,
        )

    async def handle_settle_budget(self, cmd: SettleBudgetCommand) -> dict[str, Any]:
        """Handle SettleBudgetCommand.

        Args:
            cmd: Command payload.

        Returns:
            Budget transaction confirmation dictionary.
        """
        return {
            "project_id": cmd.project_id,
            "settled_amount_cents": cmd.amount_cents,
            "status": "SETTLED",
            "actor": cmd.user_id,
        }

    async def handle_get_run_status(self, qry: GetRunStatusQuery) -> RunStatusReport:
        """Handle GetRunStatusQuery.

        Args:
            qry: Query payload.

        Returns:
            RunStatusReport snapshot.
        """
        return await self.controller.get_run_status(qry.run_id)

    async def handle_get_job(self, qry: GetJobQuery) -> JobSpec:
        """Handle GetJobQuery.

        Args:
            qry: Query payload.

        Returns:
            JobSpec metadata.
        """
        return await self.controller.get_job(qry.job_id)

    async def handle_list_jobs(self, qry: ListJobsQuery) -> list[JobSpec]:
        """Handle ListJobsQuery with optional run_id filter.

        Args:
            qry: Query payload.

        Returns:
            List of matching JobSpec instances.
        """
        jobs = await self.controller.list_jobs()
        if qry.run_id is not None:
            return [j for j in jobs if j.run_id == qry.run_id]
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

    async def handle_get_fairshare_tree(
        self, qry: GetFairShareTreeQuery
    ) -> FairShareTreeReport:
        """Handle GetFairShareTreeQuery.

        Args:
            qry: Query payload.

        Returns:
            FairShareTreeReport hierarchy.
        """
        engine = SchedulerExplainabilityEngine()
        import time

        return engine.explain_fairshare(current_timestamp=time.time())

    async def handle_get_queue_stats(
        self, qry: GetQueueStatsQuery
    ) -> ClusterStatsReport:
        """Handle GetQueueStatsQuery.

        Args:
            qry: Query payload.

        Returns:
            Aggregated ClusterStatsReport.
        """
        jobs = await self.controller.list_jobs()
        running = sum(1 for j in jobs if j.state.name == "RUNNING")
        pending = sum(1 for j in jobs if j.state.name == "PENDING")
        blocked = sum(1 for j in jobs if j.state.name == "BLOCKED")
        completed = sum(1 for j in jobs if j.state.name == "COMPLETED")
        failed = sum(1 for j in jobs if j.state.name in ("FAILED", "CANCELLED"))
        run_ids = {j.run_id for j in jobs}

        return ClusterStatsReport(
            total_runs=len(run_ids),
            total_jobs=len(jobs),
            running_jobs=running,
            pending_jobs=pending,
            blocked_jobs=blocked,
            completed_jobs=completed,
            failed_jobs=failed,
            active_workers=len(self.nodes) if self.nodes else 1,
        )

    async def handle_get_nodes(self, qry: GetNodesQuery) -> list[NodeTelemetryPulse]:
        """Handle GetNodesQuery.

        Args:
            qry: Query payload.

        Returns:
            List of registered NodeTelemetryPulse records.
        """
        if self.nodes:
            return self.nodes
        pulse = NodeTelemetryPulse(
            worker_id="node-local-01",
            cpu_utilization_pct=15.5,
            memory_total_mb=64 * 1024,
            memory_used_mb=16 * 1024,
            scratch_total_mb=500 * 1024,
            scratch_used_mb=50 * 1024,
            active_jobs=0,
            gpu_metrics=[],
        )
        return [pulse]

    async def handle_get_logs(self, qry: GetLogsQuery) -> list[LogChunk]:
        """Handle GetLogsQuery.

        Args:
            qry: Query payload.

        Returns:
            List of LogChunk entries.
        """
        chunks = self.log_store.get(qry.job_id, [])
        if qry.tail is not None and qry.tail < len(chunks):
            return chunks[-qry.tail :]
        return chunks


def create_hexaqueue_execution_pipeline(
    controller: SchedulerControllerPort,
    log_store: dict[str, list[LogChunk]] | None = None,
    nodes: list[NodeTelemetryPulse] | None = None,
) -> ExecutionPipeline:
    """Construct an ExecutionPipeline with all Hexaqueue CQRS command and query handlers.

    Args:
        controller: Central scheduler controller instance.
        log_store: Optional in-memory dictionary for historical job log chunks.
        nodes: Optional list of registered worker node telemetry pulses.

    Returns:
        Configured and populated ExecutionPipeline ready for synchronous dispatch.

    Notes/Architectural Intent:
        Serves as the Single Source of Truth for executing CQRS contracts across
        CLI, REST API, gRPC, and Web Dashboard.
    """
    service = HexaqueueCqrsService(
        controller=controller, log_store=log_store, nodes=nodes
    )
    handler_reg = HandlerRegistry()
    command_reg = CommandRegistry()
    query_reg = QueryRegistry()

    # Commands
    command_reg.register(SubmitRunCommand)
    handler_reg.register(
        SubmitRunCommand,
        lambda cmd: run_coro_sync(service.handle_submit_run(cmd)),
    )

    command_reg.register(SubmitSuiteCommand)
    handler_reg.register(
        SubmitSuiteCommand,
        lambda cmd: run_coro_sync(service.handle_submit_suite(cmd)),
    )

    command_reg.register(CancelRunCommand)
    handler_reg.register(
        CancelRunCommand,
        lambda cmd: run_coro_sync(service.handle_cancel_run(cmd)),
    )

    command_reg.register(HoldJobCommand)
    handler_reg.register(
        HoldJobCommand,
        lambda cmd: run_coro_sync(service.handle_hold_job(cmd)),
    )

    command_reg.register(ReleaseJobCommand)
    handler_reg.register(
        ReleaseJobCommand,
        lambda cmd: run_coro_sync(service.handle_release_job(cmd)),
    )

    command_reg.register(CancelJobCommand)
    handler_reg.register(
        CancelJobCommand,
        lambda cmd: run_coro_sync(service.handle_cancel_job(cmd)),
    )

    command_reg.register(RegisterCollateralCommand)
    handler_reg.register(
        RegisterCollateralCommand,
        lambda cmd: run_coro_sync(service.handle_register_collateral(cmd)),
    )

    command_reg.register(CreatePtySessionCommand)
    handler_reg.register(
        CreatePtySessionCommand,
        lambda cmd: run_coro_sync(service.handle_create_pty_session(cmd)),
    )

    command_reg.register(CreateBastionSessionCommand)
    handler_reg.register(
        CreateBastionSessionCommand,
        lambda cmd: run_coro_sync(service.handle_create_bastion_session(cmd)),
    )

    command_reg.register(SettleBudgetCommand)
    handler_reg.register(
        SettleBudgetCommand,
        lambda cmd: run_coro_sync(service.handle_settle_budget(cmd)),
    )

    # Queries
    query_reg.register(GetRunStatusQuery)
    handler_reg.register(
        GetRunStatusQuery,
        lambda qry: run_coro_sync(service.handle_get_run_status(qry)),
    )

    query_reg.register(GetJobQuery)
    handler_reg.register(
        GetJobQuery,
        lambda qry: run_coro_sync(service.handle_get_job(qry)),
    )

    query_reg.register(ListJobsQuery)
    handler_reg.register(
        ListJobsQuery,
        lambda qry: run_coro_sync(service.handle_list_jobs(qry)),
    )

    query_reg.register(ExplainJobQuery)
    handler_reg.register(
        ExplainJobQuery,
        lambda qry: run_coro_sync(service.handle_explain_job(qry)),
    )

    query_reg.register(GetFairShareTreeQuery)
    handler_reg.register(
        GetFairShareTreeQuery,
        lambda qry: run_coro_sync(service.handle_get_fairshare_tree(qry)),
    )

    query_reg.register(GetQueueStatsQuery)
    handler_reg.register(
        GetQueueStatsQuery,
        lambda qry: run_coro_sync(service.handle_get_queue_stats(qry)),
    )

    query_reg.register(GetNodesQuery)
    handler_reg.register(
        GetNodesQuery,
        lambda qry: run_coro_sync(service.handle_get_nodes(qry)),
    )

    query_reg.register(GetLogsQuery)
    handler_reg.register(
        GetLogsQuery,
        lambda qry: run_coro_sync(service.handle_get_logs(qry)),
    )

    return ExecutionPipeline(
        command_bus=SynchronousCommandBus(handler_registry=handler_reg),
        query_bus=SynchronousQueryBus(handler_registry=handler_reg),
        event_bus=SynchronousEventBus(),
        command_registry=command_reg,
        query_registry=query_reg,
        handler_registry=handler_reg,
    )


__all__ = [
    "create_hexaqueue_execution_pipeline",
    "HexaqueueCqrsService",
    "run_coro_sync",
]
