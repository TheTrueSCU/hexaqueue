"""CQRS handlers for pipeline runs and test suite lifecycle management.

Notes/Architectural Intent:
    Orchestrates DAG run submissions, suite compilation into executable DAGs,
    tenant-isolated status checks, and run cancellation.
"""

from typing import Any

from hexaqueue_core.domain.cqrs import (
    CancelRunCommand,
    GetRunStatusQuery,
    ListRunsQuery,
    RewindRunCommand,
    SubmitRunCommand,
    SubmitSuiteCommand,
)
from hexaqueue_core.domain.exceptions import PermissionDeniedError
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.domain.suite import SuiteCompiler
from hexaqueue_server.domain.memento import DagRewindReport
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission
from hexaqueue_server.infra.cqrs.common import (
    BaseCqrsService,
    _check_job_mutation_permission,
    _extract_job_owner,
)


def _stamp_jobs_owner(jobs: list[Any], owner: str) -> list[Any]:
    """Propagate run owner onto constituent jobs when not explicitly overridden."""
    if not owner or owner == "default":
        return list(jobs)
    stamped: list[Any] = []
    for job in jobs:
        updates: dict[str, Any] = {}
        if getattr(job, "owner", "default") == "default":
            updates["owner"] = owner
        if getattr(job, "user", "default") == "default":
            updates["user"] = owner
        if not any(tag.startswith("owner:") for tag in job.tags):
            updates["tags"] = [*job.tags, f"owner:{owner}"]
        stamped.append(job.model_copy(update=updates) if updates else job)
    return stamped


def _stamp_run_owner(run_spec: RunSpec, owner: str) -> RunSpec:
    """Propagate run owner onto RunSpec and its owner tag when unset."""
    run_updates: dict[str, Any] = {}
    if run_spec.owner == "default" and owner != "default":
        run_updates["owner"] = owner
    if owner != "default" and not any(
        tag.startswith("owner:") for tag in run_spec.tags
    ):
        run_updates["tags"] = [*run_spec.tags, f"owner:{owner}"]
    return run_spec.model_copy(update=run_updates) if run_updates else run_spec


def _is_run_owned_by(
    report: RunStatusReport,
    runs_map: dict[str, RunSubmission],
    user_id: str,
) -> bool:
    """Return True when the run report or its submission belongs to ``user_id``."""
    if report.owner == user_id:
        return True
    sub = runs_map.get(report.run_id)
    return sub is not None and any(
        tag.startswith("owner:") and tag.split(":", 1)[1] == user_id
        for tag in sub.run_spec.tags
    )


class RunsCqrsMixin(BaseCqrsService):
    """Mixin implementing CQRS command and query handlers for runs and suites."""

    async def handle_submit_run(self, cmd: SubmitRunCommand) -> RunStatusReport:
        """Handle SubmitRunCommand.

        Args:
            cmd: Command payload.

        Returns:
            Initial RunStatusReport.
        """
        owner = cmd.user_id or cmd.run_spec.owner or "default"
        run_spec = _stamp_run_owner(cmd.run_spec, owner)
        submission = RunSubmission(
            run_spec=run_spec,
            jobs=_stamp_jobs_owner(cmd.jobs, owner),
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
        owner = cmd.user_id or "default"
        run_spec = RunSpec(
            id=cmd.suite_spec.id,
            name=cmd.suite_spec.name or cmd.suite_spec.id,
            owner=owner,
            tags=[f"owner:{owner}"],
        )
        dependencies = {
            child_id: [dep.parent_job_id for dep in deps]
            for child_id, deps in result.dependencies.items()
        }
        submission = RunSubmission(
            run_spec=run_spec,
            jobs=_stamp_jobs_owner(result.jobs, owner),
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
        if not cmd.elevate:
            jobs = await self.controller.list_jobs()
            run_jobs = [j for j in jobs if j.run_id == cmd.run_id]
            for j in run_jobs:
                _check_job_mutation_permission(
                    j, cmd.user_id, cmd.elevate, "cancel run"
                )

        return await self.controller.cancel_run(cmd.run_id)

    async def handle_get_run_status(self, qry: GetRunStatusQuery) -> RunStatusReport:
        """Handle GetRunStatusQuery.

        Args:
            qry: Query payload.

        Returns:
            RunStatusReport snapshot.

        Raises:
            PermissionDeniedError: If unauthorized cross-tenant run status inspection is attempted.
        """
        status = await self.controller.get_run_status(qry.run_id)
        if not qry.elevate:
            jobs = await self.controller.list_jobs()
            run_jobs = [j for j in jobs if j.run_id == qry.run_id]
            is_authorized = False
            if run_jobs:
                is_authorized = any(
                    _extract_job_owner(j) == qry.user_id for j in run_jobs
                )
            else:
                runs_map = getattr(self.controller, "_runs", None)
                if runs_map and qry.run_id in runs_map:
                    run_spec = runs_map[qry.run_id].run_spec
                    is_authorized = any(
                        tag == f"owner:{qry.user_id}"
                        or (
                            tag.startswith("owner:")
                            and tag.split(":", 1)[1] == qry.user_id
                        )
                        for tag in run_spec.tags
                    )
            if not is_authorized:
                msg = (
                    f"Permission denied: You do not have access to run '{qry.run_id}'. "
                    "Explicit administrative elevation (--admin / elevate=true) is required."
                )
                raise PermissionDeniedError(msg)
        return status

    async def handle_rewind_run(self, cmd: RewindRunCommand) -> DagRewindReport:
        """Handle RewindRunCommand by rewinding target jobs and downstream dependents.

        Args:
            cmd: Command payload specifying target jobs.

        Returns:
            DagRewindReport summarizing reset, re-enqueued, and unaffected tasks.
        """
        return await self.controller.rewind_run(
            run_id=cmd.run_id,
            target_job_ids=cmd.target_job_ids,
        )

    async def handle_list_runs(self, qry: ListRunsQuery) -> list[RunStatusReport]:
        """Handle ListRunsQuery with tenant isolation.

        Args:
            qry: Query payload specifying user identity and elevation.

        Returns:
            List of authorized RunStatusReport instances.
        """
        all_runs = await self.controller.list_runs()
        if qry.elevate:
            return all_runs[: qry.limit]

        runs_map = getattr(self.controller, "_runs", {})
        authorized = [
            report
            for report in all_runs
            if _is_run_owned_by(report, runs_map, qry.user_id)
        ]
        return authorized[: qry.limit]


__all__ = [
    "RunsCqrsMixin",
]
