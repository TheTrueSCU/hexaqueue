"""Distributed cluster workflow execution engine integrating Hexaqueue and Hexaflow.

Notes/Architectural Intent:
    Implements WorkflowEnginePort by mapping Hexaflow workflow DAG steps onto
    Hexaqueue cluster jobs. Enforces CPU/RAM/GPU resource constraints, integrates
    SchedulerControllerPort for job dispatching, offloads intermediate step
    payloads exceeding 64KB to StoragePort, and coordinates durable checkpointing.
"""

import asyncio
import contextlib
import inspect
import traceback
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from hexaflow.adapters.storage.in_memory import InMemoryStateStore
from hexaflow.domain.exceptions import (
    StepNotFoundError,
    WorkflowAborted,
    WorkflowSuspended,
)
from hexaflow.domain.models import (
    StageDefinition,
    StageExecutionMode,
    StepDefinition,
    WorkflowDefinition,
    evaluate_trigger_rule,
)
from hexaflow.domain.state import (
    CheckpointRecord,
    StepContext,
    StepStatus,
    WorkflowExecutionState,
    WorkflowStatus,
)
from hexaflow.ports.engine import WorkflowEnginePort
from hexaflow.ports.storage import WorkflowStateStorePort
from hexastack_core.adapters.storage.in_memory import InMemoryStorage
from hexastack_core.ports.storage import StoragePort

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, JobStatus, TerminalOutcome
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.domain.models import RunSubmission
from hexaqueue_server.ports.controller import SchedulerControllerPort
from hexaqueue_workflow.adapters.staging.storage import (
    StoragePortArtifactStagingAdapter,
)
from hexaqueue_workflow.domain.models import (
    ArtifactReference,
    DistributedWorkflowConfig,
)
from hexaqueue_workflow.ports.staging import ArtifactStagingPort


class HexaqueueDistributedEngine(WorkflowEnginePort):
    """Distributed workflow execution engine integrating Hexaqueue cluster orchestration.

    Notes/Architectural Intent:
        Transforms Hexaflow DAG stages and steps into Hexaqueue jobs with explicit
        compute constraints (CPU, RAM, GPU), dispatches them through SchedulerControllerPort,
        stages intermediate payloads larger than the threshold via ArtifactStagingPort,
        and manages durable checkpoints for failure recovery and resumption.

    Args:
        controller: SchedulerControllerPort instance (defaults to LocalSchedulerControllerAdapter).
        staging: ArtifactStagingPort instance (defaults to StoragePortArtifactStagingAdapter with InMemoryStorage).
        state_store: WorkflowStateStorePort for checkpoint persistence (defaults to InMemoryStateStore).
        storage: Optional StoragePort if custom staging adapter is not provided.
        config: Optional DistributedWorkflowConfig parameterizing thresholds and resources.
    """

    def __init__(
        self,
        controller: SchedulerControllerPort | None = None,
        staging: ArtifactStagingPort | None = None,
        state_store: WorkflowStateStorePort | None = None,
        storage: StoragePort | None = None,
        config: DistributedWorkflowConfig | None = None,
    ) -> None:
        """Initialize HexaqueueDistributedEngine.

        Args:
            controller: Scheduler controller for job dispatch and status tracking.
            staging: Artifact staging port for handling large payloads.
            state_store: Persistence store for workflow state and step checkpoints.
            storage: Concrete StoragePort to use if default staging adapter is created.
            config: Distributed engine configuration.
        """
        self._config = config or DistributedWorkflowConfig()
        self._controller = controller or LocalSchedulerControllerAdapter(
            queue=InMemoryJobQueueAdapter()
        )
        self._store = state_store or InMemoryStateStore()

        if staging is not None:
            self._staging = staging
        else:
            storage_backend = storage or InMemoryStorage()
            self._staging = StoragePortArtifactStagingAdapter(
                storage=storage_backend, config=self._config
            )

    def run(
        self,
        workflow: WorkflowDefinition,
        initial_inputs: dict[str, Any] | None = None,
        skip_steps: set[str] | list[str] | None = None,
    ) -> WorkflowExecutionState:
        """Synchronously execute a workflow definition from start to finish.

        Args:
            workflow: Immutable specification of the workflow DAG.
            initial_inputs: Optional dictionary of input arguments.
            skip_steps: Optional collection of step names to explicitly skip.

        Returns:
            Terminal or suspended WorkflowExecutionState.
        """
        return asyncio.run(
            self.run_async(workflow, initial_inputs, skip_steps=skip_steps)
        )

    async def run_async(
        self,
        workflow: WorkflowDefinition,
        initial_inputs: dict[str, Any] | None = None,
        skip_steps: set[str] | list[str] | None = None,
    ) -> WorkflowExecutionState:
        """Asynchronously execute a workflow definition from start to finish.

        Args:
            workflow: Immutable specification of the workflow DAG.
            initial_inputs: Optional dictionary of input arguments.
            skip_steps: Optional collection of step names to explicitly skip.

        Returns:
            Terminal or suspended WorkflowExecutionState.
        """
        run_id = str(uuid4())
        state = WorkflowExecutionState(
            run_id=run_id,
            workflow_name=workflow.name,
            status=WorkflowStatus.RUNNING,
        )
        self._store.save_run(state)
        skipped = set(skip_steps or ())
        return await self._execute_workflow(
            state, workflow, initial_inputs or {}, skipped
        )

    def resume(
        self,
        run_id: str,
        workflow: WorkflowDefinition,
        patch_inputs: dict[str, Any] | None = None,
        skip_steps: set[str] | list[str] | None = None,
    ) -> WorkflowExecutionState:
        """Synchronously resume a suspended workflow run from its latest checkpoints.

        Args:
            run_id: Execution identifier of the suspended workflow run.
            workflow: WorkflowDefinition specification matching the run.
            patch_inputs: Optional override inputs for the resuming step frontier.
            skip_steps: Optional collection of step names to explicitly skip during resumption.

        Returns:
            Updated WorkflowExecutionState outcome.
        """
        return asyncio.run(
            self.resume_async(run_id, workflow, patch_inputs, skip_steps=skip_steps)
        )

    async def resume_async(
        self,
        run_id: str,
        workflow: WorkflowDefinition,
        patch_inputs: dict[str, Any] | None = None,
        skip_steps: set[str] | list[str] | None = None,
    ) -> WorkflowExecutionState:
        """Asynchronously resume a suspended workflow run from its latest checkpoints.

        Args:
            run_id: Execution identifier of the suspended workflow run.
            workflow: WorkflowDefinition specification matching the run.
            patch_inputs: Optional override inputs for the resuming step frontier.
            skip_steps: Optional collection of step names to explicitly skip during resumption.

        Returns:
            Updated WorkflowExecutionState outcome.

        Raises:
            WorkflowSuspended: If run_id is not found in state store.
        """
        state = self._store.get_run(run_id)
        if not state:
            raise WorkflowSuspended(
                run_id, "unknown", f"Workflow run '{run_id}' not found in state store."
            )

        state.status = WorkflowStatus.RUNNING
        state.error_summary = None
        self._store.save_run(state)
        skipped = set(skip_steps or ())
        return await self._execute_workflow(
            state, workflow, patch_inputs or {}, skipped
        )

    def restart(
        self,
        run_id: str,
        workflow: WorkflowDefinition,
    ) -> WorkflowExecutionState:
        """Synchronously restart a workflow execution run from the beginning.

        Args:
            run_id: Execution identifier of the run to restart.
            workflow: WorkflowDefinition specification to re-execute.

        Returns:
            Fresh WorkflowExecutionState outcome.
        """
        return asyncio.run(self.restart_async(run_id, workflow))

    async def restart_async(
        self,
        run_id: str,
        workflow: WorkflowDefinition,
    ) -> WorkflowExecutionState:
        """Asynchronously restart a workflow execution run from the beginning.

        Args:
            run_id: Execution identifier of the run to restart.
            workflow: WorkflowDefinition specification to re-execute.

        Returns:
            Fresh WorkflowExecutionState outcome.
        """
        state = WorkflowExecutionState(
            run_id=run_id,
            workflow_name=workflow.name,
            status=WorkflowStatus.RUNNING,
        )
        self._store.save_run(state)
        return await self._execute_workflow(state, workflow, {}, is_restart=True)

    def abort(
        self,
        run_id: str,
        workflow: WorkflowDefinition,
    ) -> WorkflowExecutionState:
        """Synchronously abort a workflow, unwinding compensations in reverse order.

        Args:
            run_id: Execution identifier of the workflow run to terminate.
            workflow: WorkflowDefinition containing any optional step compensations.

        Returns:
            Terminal WorkflowExecutionState marked CANCELLED.
        """
        return asyncio.run(self.abort_async(run_id, workflow))

    async def abort_async(
        self,
        run_id: str,
        workflow: WorkflowDefinition,
    ) -> WorkflowExecutionState:
        """Asynchronously abort a workflow, unwinding compensations in reverse order.

        Args:
            run_id: Execution identifier of the workflow run to terminate.
            workflow: WorkflowDefinition containing any optional step compensations.

        Returns:
            Terminal WorkflowExecutionState marked CANCELLED.

        Raises:
            WorkflowAborted: If run is not found in state store.
        """
        state = self._store.get_run(run_id)
        if not state:
            raise WorkflowAborted(f"Workflow run '{run_id}' not found.")

        # Attempt to cancel any in-flight jobs in scheduler controller
        with contextlib.suppress(Exception):
            await self._controller.cancel_run(run_id)

        checkpoints = self._store.get_checkpoints(run_id)
        for chk in reversed(checkpoints):
            if chk.status == StepStatus.COMPLETED:
                try:
                    step = workflow.get_step(chk.step_name)
                    if step.compensation:
                        raw_inputs = chk.input_payload
                        if ArtifactReference.is_artifact_envelope(raw_inputs):
                            raw_inputs = self._staging.retrieve_artifact(raw_inputs)
                        inputs_dict = raw_inputs if isinstance(raw_inputs, dict) else {}
                        ctx = StepContext(
                            run_id=run_id,
                            stage_name=chk.stage_name,
                            step_name=chk.step_name,
                            inputs=inputs_dict,
                        )
                        await self._invoke_callable(step.compensation, ctx)
                except StepNotFoundError:
                    continue

        state.status = WorkflowStatus.CANCELLED
        state.finished_at = datetime.now(UTC)
        self._store.save_run(state)
        return state

    async def _execute_workflow(
        self,
        state: WorkflowExecutionState,
        workflow: WorkflowDefinition,
        inputs: dict[str, Any],
        skipped_steps: set[str] | None = None,
        is_restart: bool = False,
    ) -> WorkflowExecutionState:
        """Main workflow execution loop advancing stage by stage."""
        cached_outputs: dict[str, Any] = {}
        active_skips = set(skipped_steps or ())

        # Populate cached outputs from existing completed checkpoints (resumption path)
        if not is_restart:
            existing_checkpoints = self._store.get_checkpoints(state.run_id)
            for chk in existing_checkpoints:
                state.step_checkpoints[chk.step_name] = chk
                if chk.status == StepStatus.COMPLETED:
                    # Retrieve from staging if necessary
                    cached_outputs[chk.step_name] = self._staging.retrieve_artifact(
                        chk.output_payload
                    )
                elif chk.status == StepStatus.SKIPPED:
                    cached_outputs[chk.step_name] = None

        # Execute stages
        for stage in workflow.stages:
            state.current_stage = stage.name
            self._store.save_run(state)

            try:
                await self._execute_stage(
                    state,
                    stage,
                    workflow,
                    cached_outputs,
                    inputs,
                    active_skips,
                    is_restart=is_restart,
                )
            except WorkflowSuspended as suspended_err:
                state.status = WorkflowStatus.SUSPENDED
                state.error_summary = str(suspended_err)
                self._store.save_run(state)
                return state

        state.status = WorkflowStatus.COMPLETED
        state.finished_at = datetime.now(UTC)
        self._store.save_run(state)
        return state

    async def _execute_stage(
        self,
        state: WorkflowExecutionState,
        stage: StageDefinition,
        workflow: WorkflowDefinition,
        cached_outputs: dict[str, Any],
        initial_inputs: dict[str, Any],
        skipped_steps: set[str],
        is_restart: bool = False,
    ) -> None:
        """Execute steps within a stage respecting sequential or concurrent execution mode."""
        if stage.execution_mode == StageExecutionMode.SEQUENTIAL:
            for step in stage.steps:
                res = await self._execute_step(
                    state,
                    stage,
                    step,
                    cached_outputs,
                    initial_inputs,
                    skipped_steps,
                    is_restart=is_restart,
                )
                cached_outputs[step.name] = res
        else:
            # CONCURRENT execution mode (DAG split / fan-out)
            tasks = [
                self._execute_step(
                    state,
                    stage,
                    step,
                    cached_outputs,
                    initial_inputs,
                    skipped_steps,
                    is_restart=is_restart,
                )
                for step in stage.steps
            ]
            results = await asyncio.gather(*tasks)
            for step, res in zip(stage.steps, results, strict=True):
                cached_outputs[step.name] = res

    async def _execute_step(
        self,
        state: WorkflowExecutionState,
        stage: StageDefinition,
        step: StepDefinition,
        cached_outputs: dict[str, Any],
        initial_inputs: dict[str, Any],
        skipped_steps: set[str],
        is_restart: bool = False,
    ) -> Any:
        """Execute an individual step with resource mapping, controller tracking, and artifact staging."""
        # 1. Resumption Check
        if not is_restart:
            existing_chk = self._store.get_checkpoint(state.run_id, step.name)
            if existing_chk and existing_chk.status in (
                StepStatus.COMPLETED,
                StepStatus.SKIPPED,
            ):
                return self._staging.retrieve_artifact(existing_chk.output_payload)

        # 2. Explicit Skip Check
        if step.name in skipped_steps:
            start_time = datetime.now(UTC)
            chk = CheckpointRecord(
                run_id=state.run_id,
                stage_name=stage.name,
                step_name=step.name,
                status=StepStatus.SKIPPED,
                attempt_number=1,
                input_payload=initial_inputs,
                output_payload=None,
                started_at=start_time,
                completed_at=start_time,
                duration_seconds=0.0,
            )
            self._store.save_checkpoint(chk)
            state.step_checkpoints[step.name] = chk
            return None

        # 3. Join Barrier Verification & Trigger Rule Evaluation
        parent_statuses: list[StepStatus] = []
        for dep in step.depends_on:
            dep_chk = state.step_checkpoints.get(dep) or self._store.get_checkpoint(
                state.run_id, dep
            )
            if not dep_chk:
                raise WorkflowSuspended(
                    run_id=state.run_id,
                    failed_step=step.name,
                    reason=f"Join barrier unsatisfied: parent step '{dep}' not evaluated.",
                )
            parent_statuses.append(dep_chk.status)

        if not evaluate_trigger_rule(step.trigger_rule, parent_statuses):
            start_time = datetime.now(UTC)
            chk = CheckpointRecord(
                run_id=state.run_id,
                stage_name=stage.name,
                step_name=step.name,
                status=StepStatus.SKIPPED,
                attempt_number=1,
                input_payload=initial_inputs,
                output_payload=None,
                started_at=start_time,
                completed_at=start_time,
                duration_seconds=0.0,
            )
            self._store.save_checkpoint(chk)
            state.step_checkpoints[step.name] = chk
            return None

        # 4. Resolve Step Inputs
        step_inputs: dict[str, Any] = dict(initial_inputs)
        for dep in step.depends_on:
            step_inputs[dep] = cached_outputs.get(dep)

        # 5. Convert step to cluster JobSpec with resource constraints
        job_spec = self._build_job_spec(state.run_id, stage.name, step)

        # Register run / job in controller
        run_submission = RunSubmission(
            run_spec=RunSpec(id=f"{state.run_id}_{step.name}", name=step.name),
            jobs=[job_spec],
            dependencies={},
        )
        with contextlib.suppress(Exception):
            await self._controller.submit_run(run_submission)

        # 6. Execute action with retry policy
        max_attempts = step.retry_policy.max_attempts if step.retry_policy else 1
        current_attempt = 1
        last_exception: Exception | None = None
        start_time = datetime.now(UTC)

        ctx = StepContext(
            run_id=state.run_id,
            stage_name=stage.name,
            step_name=step.name,
            attempt_number=current_attempt,
            inputs=step_inputs,
        )

        while current_attempt <= max_attempts:
            ctx = StepContext(
                run_id=state.run_id,
                stage_name=stage.name,
                step_name=step.name,
                attempt_number=current_attempt,
                inputs=step_inputs,
            )
            try:
                output = await self._invoke_callable(step.action, ctx)

                # Step Succeeded: update controller outcome
                await self._controller.update_job_outcome(
                    job_id=job_spec.id,
                    outcome=TerminalOutcome.COMPLETED,
                )

                # Check if output should be staged to StoragePort
                staged_output = self._staging.stage_artifact(
                    run_id=state.run_id, step_name=step.name, payload=output
                )

                # Checkpoint output payload (stores envelope if staged)
                output_for_checkpoint = (
                    staged_output.to_envelope()
                    if isinstance(staged_output, ArtifactReference)
                    else staged_output
                )

                end_time = datetime.now(UTC)
                chk = CheckpointRecord(
                    run_id=state.run_id,
                    stage_name=stage.name,
                    step_name=step.name,
                    status=StepStatus.COMPLETED,
                    attempt_number=current_attempt,
                    input_payload=step_inputs,
                    output_payload=output_for_checkpoint,
                    started_at=start_time,
                    completed_at=end_time,
                    duration_seconds=(end_time - start_time).total_seconds(),
                )
                self._store.save_checkpoint(chk)
                state.step_checkpoints[step.name] = chk
                return output

            except Exception as e:
                last_exception = e
                if (
                    step.retry_policy
                    and current_attempt < step.retry_policy.max_attempts
                ):
                    delay = step.retry_policy.calculate_delay(current_attempt)
                    await asyncio.sleep(delay)
                    current_attempt += 1
                else:
                    break

        # Step permanently failed: report to controller and suspend
        tb = (
            "".join(
                traceback.format_exception(
                    type(last_exception),
                    last_exception,
                    last_exception.__traceback__,
                )
            )
            if last_exception
            else "Unknown failure"
        )
        end_time = datetime.now(UTC)

        await self._controller.update_job_outcome(
            job_id=job_spec.id,
            outcome=TerminalOutcome.FAILED,
            reason=str(last_exception),
        )

        chk = CheckpointRecord(
            run_id=state.run_id,
            stage_name=stage.name,
            step_name=step.name,
            status=StepStatus.FAILED,
            attempt_number=current_attempt,
            input_payload=step_inputs,
            output_payload=None,
            error_traceback=tb,
            started_at=start_time,
            completed_at=end_time,
            duration_seconds=(end_time - start_time).total_seconds(),
        )
        self._store.save_checkpoint(chk)
        state.step_checkpoints[step.name] = chk

        raise WorkflowSuspended(
            run_id=state.run_id,
            failed_step=step.name,
            reason=f"Step '{step.name}' failed after {current_attempt} attempts: {last_exception}",
        )

    def _build_job_spec(
        self, run_id: str, stage_name: str, step: StepDefinition
    ) -> JobSpec:
        """Construct a JobSpec from a StepDefinition and configured mappings."""
        mapping = self._config.step_mappings.get(step.name)
        if mapping:
            cpu = mapping.cpu_cores
            mem = mapping.memory_mb
            gpu = mapping.gpu_count
            tags = list(mapping.tags)
            cmd = mapping.command or f"python -m hexaflow.step {step.name}"
            args = list(mapping.args)
            env = dict(mapping.env)
        else:
            cpu = self._config.default_cpu_cores
            mem = self._config.default_memory_mb
            gpu = self._config.default_gpu_count
            tags = ["workflow", stage_name]
            cmd = f"python -m hexaflow.step {step.name}"
            args = []
            env = {}

        return JobSpec(
            id=f"{run_id}_{step.name}",
            run_id=run_id,
            name=step.name,
            command=cmd,
            args=args,
            env=env,
            resources=ResourceRequirements(
                cpus=max(1, int(cpu)),
                ram_mb=max(128, int(mem)),
                gpus=max(0, int(gpu)),
            ),
            tags=tags,
            status=JobStatus(state=JobState.PENDING),
        )

    async def _invoke_callable(self, action: Any, ctx: StepContext) -> Any:
        """Invoke an action callable, passing StepContext or context kwargs as supported."""
        sig = inspect.signature(action)
        params = list(sig.parameters.values())

        if len(params) == 0:
            result = action()
        elif len(params) == 1 and (
            params[0].annotation is StepContext or params[0].name == "ctx"
        ):
            result = action(ctx)
        elif len(params) == 1 and params[0].name in ("inputs", "data"):
            result = action(ctx.inputs)
        else:
            # Map keyword arguments from ctx.inputs
            kwargs: dict[str, Any] = {}
            for p in params:
                if p.name in ctx.inputs:
                    kwargs[p.name] = ctx.inputs[p.name]
                elif p.name == "ctx":
                    kwargs["ctx"] = ctx
                elif p.default is not inspect.Parameter.empty:
                    kwargs[p.name] = p.default
                else:
                    kwargs[p.name] = None
            result = action(**kwargs)

        if inspect.isawaitable(result):
            return await result
        return result


__all__ = [
    "HexaqueueDistributedEngine",
]
