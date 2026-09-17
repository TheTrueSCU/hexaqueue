"""Standalone in-process scheduler controller adapter.

Notes/Architectural Intent:
    Orchestrates job queues, DAG dependency resolution, and state roll-up
    in-process without requiring external database or cluster daemon overhead.
"""

import asyncio

from hexaqueue_core.domain.dag import JobDagEngine, TriggerCondition
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import (
    JobState,
    JobStatus,
    RunState,
    TerminalOutcome,
    compute_run_outcome,
    compute_run_state,
)
from hexaqueue_core.domain.notification import (
    NotificationTrigger,
    map_lifecycle_to_trigger,
)
from hexaqueue_core.infra.notification import NotificationDispatcher
from hexaqueue_core.ports.queue import JobQueuePort
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission
from hexaqueue_server.ports.controller import SchedulerControllerPort


class LocalSchedulerControllerAdapter(SchedulerControllerPort):
    """In-process scheduler controller implementation."""

    def __init__(
        self,
        queue: JobQueuePort,
        notification_dispatcher: NotificationDispatcher | None = None,
    ) -> None:
        """Initialize controller with task queue and optional notification dispatcher.

        Args:
            queue: Underlying JobQueuePort implementation (e.g. InMemoryJobQueueAdapter).
            notification_dispatcher: Optional NotificationDispatcher for cluster lifecycle alerts.
        """
        self._queue = queue
        self._dispatcher = notification_dispatcher or NotificationDispatcher()
        self._runs: dict[str, RunSubmission] = {}
        self._jobs: dict[str, JobSpec] = {}
        self._dag_engines: dict[str, JobDagEngine] = {}
        self._lock = asyncio.Lock()

    async def submit_run(self, submission: RunSubmission) -> RunStatusReport:
        """Submit a DAG pipeline run for scheduling."""
        run_id = submission.run_spec.id

        async with self._lock:
            if run_id in self._runs:
                msg = f"Run with ID '{run_id}' is already registered"
                raise HexaqueueError(msg)

            # Build and validate DAG
            dag = JobDagEngine()
            for child_id, parents in submission.dependencies.items():
                for parent_id in parents:
                    dag.add_dependency(
                        child_job_id=child_id,
                        parent_job_id=parent_id,
                        condition=TriggerCondition.AFTER_OK,
                    )

            all_job_ids = {j.id for j in submission.jobs}
            # Throws DependencyCycleError if cyclic
            dag.validate_and_topological_sort(all_job_ids)

            self._runs[run_id] = submission
            self._dag_engines[run_id] = dag

            # Register jobs and enqueue root jobs (no prerequisites)
            for job in submission.jobs:
                self._jobs[job.id] = job
                is_ready = dag.is_job_ready(job.id, {})
                if is_ready:
                    # Advance to PENDING and enqueue
                    pending_job = JobSpec(
                        id=job.id,
                        run_id=job.run_id,
                        name=job.name,
                        command=job.command,
                        args=job.args,
                        env=job.env,
                        resources=job.resources,
                        collateral_ids=job.collateral_ids,
                        tags=job.tags,
                        notifications=job.notifications,
                        status=JobStatus(state=JobState.PENDING),
                    )
                    self._jobs[job.id] = pending_job
                    await self._queue.enqueue(pending_job)

        await self._dispatcher.async_dispatch_run_event(
            submission.run_spec, NotificationTrigger.SUBMITTED
        )

        return await self.get_run_status(run_id)

    async def get_run_status(self, run_id: str) -> RunStatusReport:
        """Retrieve aggregated run status."""
        async with self._lock:
            if run_id not in self._runs:
                msg = f"Run with ID '{run_id}' not found"
                raise HexaqueueError(msg)

            submission = self._runs[run_id]
            run_jobs = [self._jobs[j.id] for j in submission.jobs]

            job_states = [j.state for j in run_jobs]
            run_state = compute_run_state(job_states)

            job_outcomes = [j.outcome for j in run_jobs if j.outcome is not None]
            run_outcome = (
                compute_run_outcome(job_outcomes)
                if run_state in (RunState.DONE, RunState.BLOCKED)
                else None
            )

            completed = sum(
                1 for j in run_jobs if j.outcome == TerminalOutcome.COMPLETED
            )
            failed = sum(
                1
                for j in run_jobs
                if j.outcome in (TerminalOutcome.FAILED, TerminalOutcome.TIMED_OUT)
            )
            running = sum(
                1
                for j in run_jobs
                if j.state
                in (JobState.PROVISIONING, JobState.RUNNING, JobState.CLEANUP)
            )
            pending = sum(
                1
                for j in run_jobs
                if j.state in (JobState.SUBMITTED, JobState.BLOCKED, JobState.PENDING)
            )

            return RunStatusReport(
                run_id=run_id,
                state=run_state,
                outcome=run_outcome,
                total_jobs=len(run_jobs),
                completed_jobs=completed,
                failed_jobs=failed,
                running_jobs=running,
                pending_jobs=pending,
                created_at=submission.run_spec.created_at,
            )

    async def get_job(self, job_id: str) -> JobSpec:
        """Retrieve current metadata and status for an individual job."""
        async with self._lock:
            if job_id not in self._jobs:
                msg = f"Job with ID '{job_id}' not found"
                raise HexaqueueError(msg)
            return self._jobs[job_id]

    async def list_jobs(self) -> list[JobSpec]:
        """Retrieve all currently registered jobs across runs."""
        async with self._lock:
            return list(self._jobs.values())

    async def update_job_outcome(
        self,
        job_id: str,
        outcome: TerminalOutcome,
        reason: str | None = None,
    ) -> None:
        """Record terminal outcome and advance eligible downstream dependents."""
        async with self._lock:
            if job_id not in self._jobs:
                msg = f"Job with ID '{job_id}' not found"
                raise HexaqueueError(msg)

            current_job = self._jobs[job_id]
            run_id = current_job.run_id

            # Update job to terminal state
            terminal_job = JobSpec(
                id=current_job.id,
                run_id=current_job.run_id,
                name=current_job.name,
                command=current_job.command,
                args=current_job.args,
                env=current_job.env,
                resources=current_job.resources,
                collateral_ids=current_job.collateral_ids,
                tags=current_job.tags,
                notifications=current_job.notifications,
                status=JobStatus(
                    state=JobState.DONE,
                    outcome=outcome,
                    reason=reason,
                ),
            )
            self._jobs[job_id] = terminal_job

            # Dispatch job-level notification
            job_trigger = map_lifecycle_to_trigger(JobState.DONE, outcome)
            if job_trigger:
                await self._dispatcher.async_dispatch_job_event(
                    terminal_job,
                    job_trigger,
                    details={"reason": reason},
                )

            # Evaluate downstream dependents and check run completion
            if run_id in self._runs:
                submission = self._runs[run_id]
                dag = self._dag_engines[run_id]
                await self._advance_dependents(submission, dag)
                await self._check_and_notify_run_completion(submission)

    async def _advance_dependents(
        self,
        submission: RunSubmission,
        dag: JobDagEngine,
    ) -> None:
        """Evaluate DAG readiness and advance dependent tasks."""
        outcomes: dict[str, TerminalOutcome | None] = {
            j.id: self._jobs[j.id].outcome for j in submission.jobs
        }

        for job_spec in submission.jobs:
            j_id = job_spec.id
            stored = self._jobs[j_id]
            if stored.state != JobState.SUBMITTED:
                continue

            if dag.is_job_ready(j_id, outcomes):
                ready_job = JobSpec(
                    id=stored.id,
                    run_id=stored.run_id,
                    name=stored.name,
                    command=stored.command,
                    args=stored.args,
                    env=stored.env,
                    resources=stored.resources,
                    collateral_ids=stored.collateral_ids,
                    tags=stored.tags,
                    notifications=stored.notifications,
                    status=JobStatus(state=JobState.PENDING),
                )
                self._jobs[j_id] = ready_job
                await self._queue.enqueue(ready_job)
            elif dag.is_job_blocked(j_id, outcomes):
                blocked_job = JobSpec(
                    id=stored.id,
                    run_id=stored.run_id,
                    name=stored.name,
                    command=stored.command,
                    args=stored.args,
                    env=stored.env,
                    resources=stored.resources,
                    collateral_ids=stored.collateral_ids,
                    tags=stored.tags,
                    notifications=stored.notifications,
                    status=JobStatus(
                        state=JobState.BLOCKED,
                        reason="Upstream prerequisite task failed",
                    ),
                )
                self._jobs[j_id] = blocked_job

    async def _check_and_notify_run_completion(
        self,
        submission: RunSubmission,
    ) -> None:
        """Check if all jobs in the run reached terminal state and dispatch run notification."""
        run_jobs = [self._jobs[j.id] for j in submission.jobs]
        if not all(j.state == JobState.DONE for j in run_jobs):
            return

        job_outcomes = [j.outcome for j in run_jobs if j.outcome is not None]
        run_outcome = compute_run_outcome(job_outcomes)
        trigger = map_lifecycle_to_trigger(RunState.DONE, run_outcome)
        if trigger:
            completed_cnt = sum(
                1 for j in run_jobs if j.outcome == TerminalOutcome.COMPLETED
            )
            failed_cnt = sum(
                1
                for j in run_jobs
                if j.outcome in (TerminalOutcome.FAILED, TerminalOutcome.TIMED_OUT)
            )
            await self._dispatcher.async_dispatch_run_event(
                submission.run_spec,
                trigger,
                details={
                    "completed_jobs": completed_cnt,
                    "failed_jobs": failed_cnt,
                },
            )

    async def cancel_run(self, run_id: str) -> RunStatusReport:
        """Cancel run and all active / pending jobs."""
        async with self._lock:
            if run_id not in self._runs:
                msg = f"Run with ID '{run_id}' not found"
                raise HexaqueueError(msg)

            submission = self._runs[run_id]
            for job in submission.jobs:
                current = self._jobs[job.id]
                if current.state != JobState.DONE:
                    await self._queue.remove(job.id)
                    cancelled_job = JobSpec(
                        id=current.id,
                        run_id=current.run_id,
                        name=current.name,
                        command=current.command,
                        args=current.args,
                        env=current.env,
                        resources=current.resources,
                        collateral_ids=current.collateral_ids,
                        tags=current.tags,
                        notifications=current.notifications,
                        status=JobStatus(
                            state=JobState.DONE,
                            outcome=TerminalOutcome.CANCELLED,
                            reason="Run cancelled by user request",
                        ),
                    )
                    self._jobs[job.id] = cancelled_job
                    await self._dispatcher.async_dispatch_job_event(
                        cancelled_job, NotificationTrigger.CANCELLED
                    )

            await self._dispatcher.async_dispatch_run_event(
                submission.run_spec, NotificationTrigger.CANCELLED
            )

        return await self.get_run_status(run_id)


__all__ = [
    "LocalSchedulerControllerAdapter",
]
