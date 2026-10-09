"""CQRS handlers for pipeline runs and test suite lifecycle management.

Notes/Architectural Intent:
    Orchestrates DAG run submissions, suite compilation into executable DAGs,
    tenant-isolated status checks, and run cancellation.
"""

from hexaqueue_core.domain.cqrs import (
    CancelRunCommand,
    GetRunStatusQuery,
    SubmitRunCommand,
    SubmitSuiteCommand,
)
from hexaqueue_core.domain.exceptions import PermissionDeniedError
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.domain.suite import SuiteCompiler
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission
from hexaqueue_server.infra.cqrs.common import (
    BaseCqrsService,
    _check_job_mutation_permission,
    _extract_job_owner,
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


__all__ = [
    "RunsCqrsMixin",
]
