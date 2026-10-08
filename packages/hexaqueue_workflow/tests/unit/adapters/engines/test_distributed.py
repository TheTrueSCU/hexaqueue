"""Tests for HexaqueueDistributedEngine."""

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hexaflow.adapters.storage.in_memory import InMemoryStateStore
from hexaflow.domain.exceptions import WorkflowAborted, WorkflowSuspended
from hexaflow.domain.models import (
    RetryPolicy,
    StageDefinition,
    StageExecutionMode,
    StepDefinition,
    TriggerRule,
    WorkflowDefinition,
)
from hexaflow.domain.state import (
    CheckpointRecord,
    StepContext,
    StepStatus,
    WorkflowExecutionState,
    WorkflowStatus,
)
from hexastack_core.adapters.storage.in_memory import InMemoryStorage
from hexastack_core.ports.notification import NotificationPort

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.notification import (
    NotificationPolicy,
    NotificationTrigger,
)
from hexaqueue_core.infra.notification import NotificationDispatcher
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_workflow.adapters.barrier.grpc import GrpcSplitJoinBarrierAdapter
from hexaqueue_workflow.adapters.engines.distributed import (
    HexaqueueDistributedEngine,
)
from hexaqueue_workflow.adapters.staging.storage import (
    StoragePortArtifactStagingAdapter,
)
from hexaqueue_workflow.domain.barrier import (
    BarrierPartition,
    BarrierResolutionSummary,
    BarrierState,
)
from hexaqueue_workflow.domain.models import (
    ArtifactReference,
    DistributedWorkflowConfig,
    WorkflowStepJobMapping,
)


@pytest.fixture
def test_setup() -> tuple[
    HexaqueueDistributedEngine, InMemoryStorage, InMemoryStateStore
]:
    """Fixture providing an engine instance with inspectable storage and state store."""
    storage = InMemoryStorage()
    store = InMemoryStateStore()
    controller = LocalSchedulerControllerAdapter(queue=InMemoryJobQueueAdapter())
    config = DistributedWorkflowConfig(
        artifact_threshold_bytes=100,  # low threshold for testing staging
        step_mappings={
            "heavy_step": WorkflowStepJobMapping(
                step_name="heavy_step",
                cpu_cores=8.0,
                memory_mb=16384,
                gpu_count=2,
                tags=["hpc", "gpu"],
            )
        },
    )
    staging = StoragePortArtifactStagingAdapter(storage=storage, config=config)
    engine = HexaqueueDistributedEngine(
        controller=controller,
        staging=staging,
        state_store=store,
        config=config,
    )
    return engine, storage, store


def test_basic_sequential_run(test_setup: tuple[Any, Any, Any]) -> None:
    """Verify synchronous execution of sequential stages and steps."""
    engine, storage, store = test_setup

    def step_one(ctx: StepContext) -> dict[str, str]:
        return {"step1": "done"}

    def step_two(ctx: StepContext) -> dict[str, str]:
        val = ctx.inputs.get("step_one", {}).get("step1", "")
        return {"step2": f"{val}_processed"}

    workflow = WorkflowDefinition(
        name="test_sequential",
        stages=[
            StageDefinition(
                name="stage_1",
                steps=[
                    StepDefinition(name="step_one", action=step_one),
                ],
            ),
            StageDefinition(
                name="stage_2",
                steps=[
                    StepDefinition(
                        name="step_two",
                        action=step_two,
                        depends_on=["step_one"],
                    ),
                ],
            ),
        ],
    )

    state = engine.run(workflow)
    assert state.status == WorkflowStatus.COMPLETED
    assert "step_one" in state.step_checkpoints
    assert "step_two" in state.step_checkpoints

    chk1 = state.step_checkpoints["step_one"]
    assert chk1.status == StepStatus.COMPLETED
    assert chk1.output_payload == {"step1": "done"}

    chk2 = state.step_checkpoints["step_two"]
    assert chk2.status == StepStatus.COMPLETED
    assert chk2.output_payload == {"step2": "done_processed"}


@pytest.mark.asyncio
async def test_concurrent_dag_split_and_artifact_staging(
    test_setup: tuple[Any, Any, Any],
) -> None:
    """Verify concurrent DAG split steps with large payload offloading to storage."""
    engine, storage, store = test_setup

    def root_step() -> dict[str, Any]:
        # Produces large payload exceeding 100 byte threshold
        return {"large_data": list(range(200))}

    def split_a(ctx: StepContext) -> str:
        data = ctx.inputs["root_step"]["large_data"]
        return f"split_a_count_{len(data)}"

    def split_b(ctx: StepContext) -> str:
        data = ctx.inputs["root_step"]["large_data"]
        return f"split_b_sum_{sum(data)}"

    def join_step(ctx: StepContext) -> dict[str, str]:
        return {
            "a": ctx.inputs["split_a"],
            "b": ctx.inputs["split_b"],
        }

    workflow = WorkflowDefinition(
        name="test_split_join",
        stages=[
            StageDefinition(
                name="root_stage",
                steps=[
                    StepDefinition(name="root_step", action=root_step),
                ],
            ),
            StageDefinition(
                name="split_stage",
                execution_mode=StageExecutionMode.CONCURRENT_ALL,
                steps=[
                    StepDefinition(
                        name="split_a",
                        action=split_a,
                        depends_on=["root_step"],
                    ),
                    StepDefinition(
                        name="split_b",
                        action=split_b,
                        depends_on=["root_step"],
                    ),
                ],
            ),
            StageDefinition(
                name="join_stage",
                steps=[
                    StepDefinition(
                        name="join_step",
                        action=join_step,
                        depends_on=["split_a", "split_b"],
                    ),
                ],
            ),
        ],
    )

    state = await engine.run_async(workflow)
    assert state.status == WorkflowStatus.COMPLETED

    root_chk = state.step_checkpoints["root_step"]
    assert root_chk.status == StepStatus.COMPLETED
    # Verify root_step output was staged to storage because len >= 100 bytes
    assert ArtifactReference.is_artifact_envelope(root_chk.output_payload)
    envelope = root_chk.output_payload
    assert "artifacts/" in envelope["storage_uri"]
    assert envelope["size_bytes"] >= 100

    join_chk = state.step_checkpoints["join_step"]
    assert join_chk.status == StepStatus.COMPLETED
    assert join_chk.output_payload == {
        "a": "split_a_count_200",
        "b": "split_b_sum_19900",
    }


@pytest.mark.asyncio
async def test_step_failure_and_resumption(
    test_setup: tuple[Any, Any, Any],
) -> None:
    """Verify suspension upon step failure and subsequent resumption after fix."""
    engine, storage, store = test_setup
    attempts = 0

    def step_succeed() -> str:
        return "initial_ok"

    def step_flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError(f"Transient error #{attempts}")
        return "recovered_ok"

    workflow = WorkflowDefinition(
        name="test_retry_and_resume",
        stages=[
            StageDefinition(
                name="stage_1",
                steps=[
                    StepDefinition(name="step_succeed", action=step_succeed),
                ],
            ),
            StageDefinition(
                name="stage_2",
                steps=[
                    StepDefinition(
                        name="step_flaky",
                        action=step_flaky,
                        retry_policy=RetryPolicy(
                            max_attempts=2, initial_delay_seconds=0.01
                        ),
                        depends_on=["step_succeed"],
                    ),
                ],
            ),
        ],
    )

    # First run fails on step_flaky after 2 attempts
    state = await engine.run_async(workflow)
    assert state.status == WorkflowStatus.SUSPENDED
    assert state.step_checkpoints["step_succeed"].status == StepStatus.COMPLETED
    assert state.step_checkpoints["step_flaky"].status == StepStatus.FAILED
    assert attempts == 2

    # Resuming run: step_succeed should not be re-run, step_flaky should attempt again and succeed (attempt 3)
    resumed_state = await engine.resume_async(run_id=state.run_id, workflow=workflow)
    assert resumed_state.status == WorkflowStatus.COMPLETED
    assert resumed_state.step_checkpoints["step_flaky"].status == StepStatus.COMPLETED
    assert resumed_state.step_checkpoints["step_flaky"].output_payload == "recovered_ok"
    assert attempts == 3


@pytest.mark.asyncio
async def test_explicit_skip_steps(test_setup: tuple[Any, Any, Any]) -> None:
    """Verify that explicitly skipped steps are marked SKIPPED immediately."""
    engine, storage, store = test_setup
    executed = False

    def skip_me() -> str:
        nonlocal executed
        executed = True
        return "not skipped"

    def normal_step() -> str:
        return "normal"

    workflow = WorkflowDefinition(
        name="test_skips",
        stages=[
            StageDefinition(
                name="stage_1",
                steps=[
                    StepDefinition(name="skip_me", action=skip_me),
                    StepDefinition(name="normal_step", action=normal_step),
                ],
            ),
        ],
    )

    state = await engine.run_async(workflow, skip_steps={"skip_me"})
    assert state.status == WorkflowStatus.COMPLETED
    assert executed is False
    assert state.step_checkpoints["skip_me"].status == StepStatus.SKIPPED
    assert state.step_checkpoints["normal_step"].status == StepStatus.COMPLETED


@pytest.mark.asyncio
async def test_trigger_rules(test_setup: tuple[Any, Any, Any]) -> None:
    """Verify trigger rules (e.g. ALL_FAILED skipped when parent succeeded)."""
    engine, storage, store = test_setup

    def parent_step() -> str:
        return "ok"

    def error_handler() -> str:
        return "handled"

    workflow = WorkflowDefinition(
        name="test_trigger_rules",
        stages=[
            StageDefinition(
                name="stage_1",
                steps=[
                    StepDefinition(name="parent_step", action=parent_step),
                ],
            ),
            StageDefinition(
                name="stage_2",
                steps=[
                    StepDefinition(
                        name="error_handler",
                        action=error_handler,
                        trigger_rule=TriggerRule.ALL_FAILED,
                        depends_on=["parent_step"],
                    ),
                ],
            ),
        ],
    )

    state = await engine.run_async(workflow)
    assert state.status == WorkflowStatus.COMPLETED
    assert state.step_checkpoints["error_handler"].status == StepStatus.SKIPPED


@pytest.mark.asyncio
async def test_restart_workflow(test_setup: tuple[Any, Any, Any]) -> None:
    """Verify restart resets the workflow state from scratch."""
    engine, storage, store = test_setup
    count = 0

    def counter_step() -> int:
        nonlocal count
        count += 1
        return count

    workflow = WorkflowDefinition(
        name="test_restart",
        stages=[
            StageDefinition(
                name="stage_1",
                steps=[
                    StepDefinition(name="counter_step", action=counter_step),
                ],
            ),
        ],
    )

    state1 = await engine.run_async(workflow)
    assert state1.status == WorkflowStatus.COMPLETED
    assert count == 1

    state2 = await engine.restart_async(run_id=state1.run_id, workflow=workflow)
    assert state2.status == WorkflowStatus.COMPLETED
    assert count == 2


@pytest.mark.asyncio
async def test_abort_with_compensation(test_setup: tuple[Any, Any, Any]) -> None:
    """Verify abort cancels run and triggers compensations in reverse order."""
    engine, storage, store = test_setup
    compensated: list[str] = []

    def comp_a(ctx: StepContext) -> None:
        compensated.append("comp_a")

    def comp_b(ctx: StepContext) -> None:
        compensated.append("comp_b")

    workflow = WorkflowDefinition(
        name="test_abort",
        stages=[
            StageDefinition(
                name="stage_1",
                steps=[
                    StepDefinition(
                        name="step_a", action=lambda: "a", compensation=comp_a
                    ),
                    StepDefinition(
                        name="step_b", action=lambda: "b", compensation=comp_b
                    ),
                ],
            ),
        ],
    )

    state = await engine.run_async(workflow)
    assert state.status == WorkflowStatus.COMPLETED

    cancelled_state = await engine.abort_async(run_id=state.run_id, workflow=workflow)
    assert cancelled_state.status == WorkflowStatus.CANCELLED
    # Unwound in reverse order: step_b then step_a
    assert compensated == ["comp_b", "comp_a"]


def test_synchronous_wrappers(test_setup: tuple[Any, Any, Any]) -> None:
    """Verify sync resume, restart, and abort wrappers."""
    engine, storage, store = test_setup

    workflow = WorkflowDefinition(
        name="test_sync_wrappers",
        stages=[
            StageDefinition(
                name="stage_1",
                steps=[
                    StepDefinition(name="step_1", action=lambda: "sync_ok"),
                ],
            ),
        ],
    )

    state = engine.run(workflow)
    assert state.status == WorkflowStatus.COMPLETED

    resumed = engine.resume(state.run_id, workflow)
    assert resumed.status == WorkflowStatus.COMPLETED

    restarted = engine.restart(state.run_id, workflow)
    assert restarted.status == WorkflowStatus.COMPLETED

    aborted = engine.abort(state.run_id, workflow)
    assert aborted.status == WorkflowStatus.CANCELLED


def test_resume_not_found(test_setup: tuple[Any, Any, Any]) -> None:
    """Verify WorkflowSuspended raised when resuming a non-existent run."""
    engine, storage, store = test_setup
    workflow = WorkflowDefinition(name="dummy", stages=[])

    with pytest.raises(WorkflowSuspended, match="not found in state store"):
        engine.resume("non-existent-id", workflow)


def test_abort_not_found(test_setup: tuple[Any, Any, Any]) -> None:
    """Verify WorkflowAborted raised when aborting a non-existent run."""
    engine, storage, store = test_setup
    workflow = WorkflowDefinition(name="dummy", stages=[])

    with pytest.raises(WorkflowAborted, match="not found"):
        engine.abort("non-existent-id", workflow)


def test_default_engine_initialization() -> None:
    """Verify HexaqueueDistributedEngine default dependencies instantiate cleanly."""
    engine = HexaqueueDistributedEngine()
    workflow = WorkflowDefinition(
        name="test_default_init",
        stages=[
            StageDefinition(
                name="stage_1",
                steps=[
                    StepDefinition(name="step_default", action=lambda: "default_ok"),
                ],
            )
        ],
    )
    state = engine.run(workflow)
    assert state.status == WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_action_callable_signature_variations() -> None:
    """Verify _invoke_callable handles diverse signature patterns."""
    engine = HexaqueueDistributedEngine()

    async def async_no_args() -> str:
        return "async_done"

    def sync_inputs_arg(inputs: dict[str, Any]) -> str:
        return f"inputs_{inputs.get('param', 'none')}"

    def sync_kwarg_mapping(
        param: str = "default_val", ctx: StepContext | None = None
    ) -> str:
        return f"kwarg_{param}_{ctx.step_name if ctx else 'no_ctx'}"

    workflow = WorkflowDefinition(
        name="test_signatures",
        stages=[
            StageDefinition(
                name="stage_sig",
                steps=[
                    StepDefinition(name="step_async", action=async_no_args),
                    StepDefinition(name="step_inputs", action=sync_inputs_arg),
                    StepDefinition(name="step_kwargs", action=sync_kwarg_mapping),
                ],
            )
        ],
    )
    state = await engine.run_async(workflow, initial_inputs={"param": "hello"})
    assert state.status == WorkflowStatus.COMPLETED
    assert state.step_checkpoints["step_async"].output_payload == "async_done"
    assert state.step_checkpoints["step_inputs"].output_payload == "inputs_hello"
    assert (
        "kwarg_hello_step_kwargs"
        in state.step_checkpoints["step_kwargs"].output_payload
    )


@pytest.mark.asyncio
async def test_step_mapping_with_custom_command_and_env() -> None:
    """Verify custom step mapping sets up job resources, env, and args."""
    config = DistributedWorkflowConfig(
        step_mappings={
            "custom_step": WorkflowStepJobMapping(
                step_name="custom_step",
                cpu_cores=4.0,
                memory_mb=2048,
                gpu_count=1,
                tags=["fast", "nvme"],
                command="custom_binary",
                args=["--flag"],
                env={"MY_VAR": "val"},
            )
        }
    )
    engine = HexaqueueDistributedEngine(config=config)
    workflow = WorkflowDefinition(
        name="test_custom_mapping",
        stages=[
            StageDefinition(
                name="stage_map",
                steps=[
                    StepDefinition(name="custom_step", action=lambda: "mapped_ok"),
                ],
            )
        ],
    )
    state = await engine.run_async(workflow)
    assert state.status == WorkflowStatus.COMPLETED

    job = await engine._controller.get_job(f"{state.run_id}_custom_step")
    assert job.command == "custom_binary"
    assert job.args == ["--flag"]
    assert job.env == {"MY_VAR": "val"}
    assert job.resources.cpus == 4
    assert job.resources.ram_mb == 2048
    assert job.resources.gpus == 1
    assert "fast" in job.tags


@pytest.mark.asyncio
async def test_resuming_with_skipped_parent(test_setup: tuple[Any, Any, Any]) -> None:
    """Verify resumption handles skipped checkpoints without errors."""
    engine, storage, store = test_setup

    workflow = WorkflowDefinition(
        name="test_resume_skipped",
        stages=[
            StageDefinition(
                name="stage_1",
                steps=[
                    StepDefinition(name="step_a", action=lambda: "a"),
                    StepDefinition(name="step_b", action=lambda: "b"),
                ],
            ),
        ],
    )

    state = await engine.run_async(workflow, skip_steps={"step_a"})
    assert state.status == WorkflowStatus.COMPLETED
    assert state.step_checkpoints["step_a"].status == StepStatus.SKIPPED

    # Resuming should read step_a as SKIPPED and populate cached_outputs with None
    resumed = await engine.resume_async(state.run_id, workflow)
    assert resumed.status == WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_distributed_engine_dynamic_mapped_step(
    test_setup: tuple[Any, Any, Any],
) -> None:
    """Verify dynamic step mapping (@wf.map_step) executes and synchronizes at join barrier."""
    engine, storage, store = test_setup

    def generate_numbers() -> list[int]:
        return [10, 20, 30]

    def square(item: int) -> int:
        return item * item

    workflow = WorkflowDefinition(
        name="test_mapped_flow",
        stages=[
            StageDefinition(
                name="stage_gen",
                steps=[
                    StepDefinition(name="gen", action=generate_numbers),
                ],
            ),
            StageDefinition(
                name="stage_map",
                steps=[
                    StepDefinition(
                        name="process_items",
                        action=square,
                        depends_on=["gen"],
                        is_mapped=True,
                        map_over="gen",
                    ),
                ],
            ),
        ],
    )

    state = await engine.run_async(workflow)
    assert state.status == WorkflowStatus.COMPLETED

    chk = state.step_checkpoints["process_items"]
    assert chk.status == StepStatus.COMPLETED
    assert chk.output_payload == [100, 400, 900]

    sub_chk_0 = store.get_checkpoint(state.run_id, "process_items[0]")
    assert sub_chk_0 is not None
    assert sub_chk_0.output_payload == 100


@pytest.mark.asyncio
async def test_distributed_engine_mapped_step_concurrency_limit(
    test_setup: tuple[Any, Any, Any],
) -> None:
    """Verify mapped step with concurrency_limit throttles execution."""
    engine, storage, store = test_setup
    active_count = 0
    max_active = 0

    async def throttled_task(item: int) -> int:
        nonlocal active_count, max_active
        active_count += 1
        max_active = max(max_active, active_count)
        await asyncio.sleep(0.01)
        active_count -= 1
        return item * 2

    workflow = WorkflowDefinition(
        name="test_concurrency_flow",
        stages=[
            StageDefinition(
                name="stage_map",
                steps=[
                    StepDefinition(
                        name="throttled",
                        action=throttled_task,
                        is_mapped=True,
                        map_over="items",
                        concurrency_limit=2,
                    ),
                ],
            ),
        ],
    )

    state = await engine.run_async(
        workflow, initial_inputs={"items": [1, 2, 3, 4, 5, 6]}
    )
    assert state.status == WorkflowStatus.COMPLETED
    assert max_active <= 2
    assert state.step_checkpoints["throttled"].output_payload == [2, 4, 6, 8, 10, 12]


@pytest.mark.asyncio
async def test_distributed_engine_mapped_step_empty(
    test_setup: tuple[Any, Any, Any],
) -> None:
    """Verify mapped step over empty collection completes with empty outputs."""
    engine, storage, store = test_setup

    workflow = WorkflowDefinition(
        name="test_empty_map",
        stages=[
            StageDefinition(
                name="stage_map",
                steps=[
                    StepDefinition(
                        name="empty_proc",
                        action=lambda item: item + 1,
                        is_mapped=True,
                        map_over="empty_list",
                    ),
                ],
            ),
        ],
    )

    state = await engine.run_async(workflow, initial_inputs={"empty_list": []})
    assert state.status == WorkflowStatus.COMPLETED
    assert state.step_checkpoints["empty_proc"].output_payload == []


@pytest.mark.asyncio
async def test_distributed_engine_mapped_step_errors(
    test_setup: tuple[Any, Any, Any],
) -> None:
    """Verify error conditions on missing or non-iterable map targets."""
    engine, storage, store = test_setup

    workflow_missing = WorkflowDefinition(
        name="test_missing_map",
        stages=[
            StageDefinition(
                name="stage_map",
                steps=[
                    StepDefinition(
                        name="bad_step",
                        action=lambda item: item,
                        is_mapped=True,
                        map_over="non_existent",
                    ),
                ],
            ),
        ],
    )

    state_missing = await engine.run_async(workflow_missing)
    assert state_missing.status == WorkflowStatus.SUSPENDED
    assert "not found in inputs" in (state_missing.error_summary or "")

    workflow_non_iter = WorkflowDefinition(
        name="test_non_iter",
        stages=[
            StageDefinition(
                name="stage_map",
                steps=[
                    StepDefinition(
                        name="bad_step",
                        action=lambda item: item,
                        is_mapped=True,
                        map_over="scalar",
                    ),
                ],
            ),
        ],
    )

    state_non_iter = await engine.run_async(
        workflow_non_iter, initial_inputs={"scalar": 12345}
    )
    assert state_non_iter.status == WorkflowStatus.SUSPENDED
    assert "is not iterable" in (state_non_iter.error_summary or "")


@pytest.mark.asyncio
async def test_distributed_engine_step_notifications_success() -> None:
    """Verify notification dispatcher triggers upon step started and completed."""
    mock_port = MagicMock(spec=NotificationPort)
    mock_port.notify.return_value = True
    dispatcher = NotificationDispatcher(notification_port=mock_port)

    policy = NotificationPolicy(
        targets=["slack://workflows"],
        triggers=NotificationTrigger.STARTED | NotificationTrigger.COMPLETED,
    )
    config = DistributedWorkflowConfig(
        default_notifications=[policy],
    )
    engine = HexaqueueDistributedEngine(
        config=config,
        notification_dispatcher=dispatcher,
    )

    workflow = WorkflowDefinition(
        name="notif_wf",
        stages=[
            StageDefinition(
                name="stage_main",
                steps=[
                    StepDefinition(name="task_ok", action=lambda: {"result": 42}),
                ],
            ),
        ],
    )

    state = await engine.run_async(workflow)
    assert state.status == WorkflowStatus.COMPLETED

    # Check notification calls: step STARTED, step COMPLETED, stage COMPLETED (default policies)
    titles = [call[1]["title"] for call in mock_port.notify.call_args_list]
    has_started = any("STARTED" in t and "task_ok" in t for t in titles)
    has_completed = any("COMPLETED" in t and "task_ok" in t for t in titles)
    assert has_started is True
    assert has_completed is True


@pytest.mark.asyncio
async def test_distributed_engine_step_notifications_failure() -> None:
    """Verify notification dispatcher triggers upon step failure."""
    mock_port = MagicMock(spec=NotificationPort)
    mock_port.notify.return_value = True
    dispatcher = NotificationDispatcher(notification_port=mock_port)

    policy = NotificationPolicy(
        targets=["pagerduty://wf-alerts"],
        triggers=NotificationTrigger.ERRORS,
    )
    config = DistributedWorkflowConfig(
        default_notifications=[policy],
    )
    engine = HexaqueueDistributedEngine(
        config=config,
        notification_dispatcher=dispatcher,
    )

    def failing_action() -> None:
        raise RuntimeError("simulated cluster step failure")

    workflow = WorkflowDefinition(
        name="failing_wf",
        stages=[
            StageDefinition(
                name="stage_err",
                steps=[
                    StepDefinition(name="task_fail", action=failing_action),
                ],
            ),
        ],
    )

    state = await engine.run_async(workflow)
    assert state.status == WorkflowStatus.SUSPENDED

    titles = [call[1]["title"] for call in mock_port.notify.call_args_list]
    has_failed = any("FAILED" in t and "task_fail" in t for t in titles)
    assert has_failed is True


def test_hexaqueue_distributed_engine_close() -> None:
    """Verify close cleanly shuts down engine resources without error."""
    engine = HexaqueueDistributedEngine()
    engine.close()


@pytest.mark.asyncio
async def test_invoke_callable_signature_permutations() -> None:
    """Verify _invoke_callable parameter matching across all supported signatures."""
    engine = HexaqueueDistributedEngine()
    ctx = StepContext(
        run_id="run-sig",
        stage_name="stage-sig",
        step_name="step-sig",
        inputs={"item": 42, "k": "val_k", "a": 10},
    )

    # 1. Zero arguments
    res_zero = await engine._invoke_callable(lambda: "zero", ctx)
    assert res_zero == "zero"

    # 2. Single argument annotated as StepContext (name != 'ctx')
    def action_annotated(my_ctx: StepContext) -> str:
        return f"annotated_{my_ctx.step_name}"

    res_ann = await engine._invoke_callable(action_annotated, ctx)
    assert res_ann == "annotated_step-sig"

    # 3. Single argument named 'ctx' without annotation
    def action_ctx_name(ctx) -> str:
        return f"named_{ctx.step_name}"

    res_name = await engine._invoke_callable(action_ctx_name, ctx)
    assert res_name == "named_step-sig"

    # 4. Single argument named 'inputs'
    def action_inputs(inputs) -> str:
        return f"in_{inputs['k']}"

    res_in = await engine._invoke_callable(action_inputs, ctx)
    assert res_in == "in_val_k"

    # 5. Single argument named 'data'
    def action_data(data) -> str:
        return f"data_{data['k']}"

    res_data = await engine._invoke_callable(action_data, ctx)
    assert res_data == "data_val_k"

    # 6. Single argument unpacking item (name not in inputs)
    def action_item(x) -> int:
        return x * 2

    res_item = await engine._invoke_callable(action_item, ctx)
    assert res_item == 84

    # 7. Keyword arguments with defaults and context mapping
    def action_kwargs(a: int, b: int = 5, ctx=None) -> int:
        assert ctx is not None
        return a + b

    res_kw = await engine._invoke_callable(action_kwargs, ctx)
    assert res_kw == 15


def test_sequential_stage_execution_order_and_dependencies(test_setup) -> None:
    """Verify sequential stages execute steps in order passing outputs."""
    engine, storage, store = test_setup
    order = []

    def s1(ctx: StepContext) -> str:
        order.append("s1")
        return "out1"

    def s2(ctx: StepContext) -> str:
        order.append("s2")
        assert ctx.inputs.get("s1") == "out1"
        return "out2"

    wf = WorkflowDefinition(
        name="seq_order",
        stages=[
            StageDefinition(
                name="stage_seq",
                execution_mode=StageExecutionMode.SEQUENTIAL,
                steps=[
                    StepDefinition(name="s1", action=s1),
                    StepDefinition(name="s2", action=s2, depends_on=["s1"]),
                ],
            )
        ],
    )
    res = engine.run(wf)
    assert res.status == WorkflowStatus.COMPLETED
    assert order == ["s1", "s2"]


@pytest.mark.asyncio
async def test_concurrent_stage_zip_strict(test_setup: tuple[Any, Any, Any]) -> None:
    """Verify zip strict=True raises ValueError on length mismatch during concurrent gather."""
    engine, storage, store = test_setup
    wf = WorkflowDefinition(
        name="gather_strict",
        stages=[
            StageDefinition(
                name="stg_conc",
                execution_mode=StageExecutionMode.CONCURRENT_ALL,
                steps=[
                    StepDefinition(name="s1", action=lambda ctx: 1),
                    StepDefinition(name="s2", action=lambda ctx: 2),
                ],
            )
        ],
    )
    state = WorkflowExecutionState(run_id="run-strict", workflow_name="gather_strict")

    # Mock gather returning length mismatch (1 result for 2 steps)
    fut = asyncio.Future()
    fut.set_result([1])
    fut_step = asyncio.Future()
    fut_step.set_result(None)

    def _mock_gather(*tasks: Any, **_kwargs: Any) -> asyncio.Future:
        for t in tasks:
            if asyncio.iscoroutine(t):
                t.close()
        return fut

    with (
        patch("asyncio.gather", side_effect=_mock_gather),
        patch.object(engine, "_execute_step", new=MagicMock(return_value=fut_step)),
        pytest.raises(ValueError),
    ):
        await engine._execute_stage(
            state=state,
            stage=wf.stages[0],
            workflow=wf,
            cached_outputs={},
            initial_inputs={},
            skipped_steps=set(),
        )


def test_step_retry_max_attempts_exact_bound(test_setup) -> None:
    """Verify retry policy breaks immediately when current_attempt == max_attempts."""
    engine, storage, store = test_setup
    attempts = 0

    def fail_action(ctx: StepContext) -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("simulated error")

    wf = WorkflowDefinition(
        name="retry_bound_wf",
        stages=[
            StageDefinition(
                name="stg_retry",
                steps=[
                    StepDefinition(
                        name="fail_step",
                        action=fail_action,
                        retry_policy=RetryPolicy(
                            max_attempts=1, initial_delay_seconds=0.01
                        ),
                    )
                ],
            )
        ],
    )
    res = engine.run(wf)
    assert res.status == WorkflowStatus.SUSPENDED
    assert attempts == 1


@pytest.mark.asyncio
async def test_mapped_step_concurrency_and_empty_items(test_setup) -> None:
    """Verify mapped step concurrency limits, empty items return, and partition node_id modulo."""
    from hexaflow.domain.state import WorkflowExecutionState

    engine, storage, store = test_setup
    state = WorkflowExecutionState(run_id="run-map-limits", workflow_name="mapped_wf")
    stage = StageDefinition(name="stg_map", steps=[])

    # 1. Empty items returns []
    step_empty = StepDefinition(
        name="m_empty", action=lambda x: x, is_mapped=True, map_over="items"
    )
    res_empty = await engine._execute_mapped_step(
        state=state,
        stage=stage,
        step=step_empty,
        cached_outputs={},
        initial_inputs={},
        step_inputs={"items": []},
    )
    assert res_empty == []

    # 2. Concurrency limit = 1 and limit <= 0
    step_limit_1 = StepDefinition(
        name="m_lim1",
        action=lambda x: x * 2,
        is_mapped=True,
        map_over="items",
        concurrency_limit=1,
    )
    res_lim1 = await engine._execute_mapped_step(
        state=state,
        stage=stage,
        step=step_limit_1,
        cached_outputs={},
        initial_inputs={},
        step_inputs={"items": [10, 20]},
    )
    assert res_lim1 == [20, 40]

    # 3. Concurrency limit = 0 (no semaphore)
    step_limit_0 = StepDefinition(
        name="m_lim0",
        action=lambda x: x + 1,
        is_mapped=True,
        map_over="items",
        concurrency_limit=0,
    )
    res_lim0 = await engine._execute_mapped_step(
        state=state,
        stage=stage,
        step=step_limit_0,
        cached_outputs={},
        initial_inputs={},
        step_inputs={"items": [5]},
    )
    assert res_lim0 == [6]

    # 4. Verify sub-step partition node_id modulo (node-1 for idx=1)
    chk_sub = state.step_checkpoints.get("m_lim1[1]")
    assert chk_sub is not None
    assert chk_sub.status == StepStatus.COMPLETED


@pytest.mark.asyncio
async def test_resumption_and_barrier_trigger_evaluation(
    test_setup: tuple[Any, Any, Any],
) -> None:
    """Verify restart bypasses checkpoints and trigger rule failure returns False."""
    engine, storage, store = test_setup
    state = WorkflowExecutionState(run_id="run-res-test", workflow_name="wf-res")

    now = datetime.now(UTC)
    chk_completed = CheckpointRecord(
        run_id="run-res-test",
        stage_name="s1",
        step_name="step_comp",
        status=StepStatus.COMPLETED,
        output_payload="cached_value",
        started_at=now,
        completed_at=now,
    )
    chk_skipped = CheckpointRecord(
        run_id="run-res-test",
        stage_name="s1",
        step_name="step_skip",
        status=StepStatus.SKIPPED,
        started_at=now,
        completed_at=now,
    )
    store.save_checkpoint(chk_completed)
    store.save_checkpoint(chk_skipped)

    stage = StageDefinition(name="s1", steps=[])
    step_c = StepDefinition(name="step_comp", action=lambda ctx: "new_val")

    # When not restart -> cached output returned
    handled, val = engine._check_step_cached_or_skipped(
        state, stage, step_c, {}, set(), is_restart=False
    )
    assert handled is True
    assert val == "cached_value"

    # When is_restart -> not cached
    handled_re, val_re = engine._check_step_cached_or_skipped(
        state, stage, step_c, {}, set(), is_restart=True
    )
    assert handled_re is False

    # Check _execute_step returning cached value directly (line 534)
    step_val = await engine._execute_step(
        state, stage, step_c, {}, {}, set(), is_restart=False
    )
    assert step_val == "cached_value"

    # End-to-end resumption through _execute_workflow
    step_downstream = StepDefinition(
        name="s_down",
        action=lambda ctx: str(ctx.inputs.get("step_comp")) + "_done",
        depends_on=["step_comp"],
    )
    wf_res = WorkflowDefinition(
        name="wf_res_e2e",
        stages=[
            StageDefinition(name="stg1", steps=[step_c]),
            StageDefinition(name="stg2", steps=[step_downstream]),
        ],
    )
    store.save_run(state)
    res_e2e = await engine.resume_async("run-res-test", wf_res)
    assert res_e2e.status == WorkflowStatus.COMPLETED
    assert res_e2e.step_checkpoints["s_down"].output_payload == "cached_value_done"

    # Check barrier trigger rule returning False
    step_trigger_none = StepDefinition(
        name="step_fail_trig",
        action=lambda ctx: None,
        depends_on=["step_skip"],
        trigger_rule=TriggerRule.ALL_SUCCESS,  # parent was SKIPPED, so trigger rule fails
    )
    res_trig = engine._check_barrier_and_trigger(state, stage, step_trigger_none, {})
    assert res_trig is False

    # Barrier trigger rule fallback to _store when state.step_checkpoints is empty
    state_empty_chk = WorkflowExecutionState(
        run_id="run-res-test", workflow_name="wf-res"
    )
    step_dep_store = StepDefinition(
        name="step_dep_store",
        action=lambda ctx: None,
        depends_on=["step_comp"],
        trigger_rule=TriggerRule.ALL_SUCCESS,
    )
    can_run = engine._check_barrier_and_trigger(
        state_empty_chk, stage, step_dep_store, {}
    )
    assert can_run is True


@pytest.mark.asyncio
async def test_mapped_sub_step_resumption_and_node_modulo(
    test_setup: tuple[Any, Any, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify sub-step resumption, direct return value, and partition node_id modulo."""
    engine, storage, store = test_setup
    state = WorkflowExecutionState(run_id="run-sub-map", workflow_name="sub_wf")
    stage = StageDefinition(name="stg_map", steps=[])
    now = datetime.now(UTC)

    # 1. Pre-checkpoint sub-step [0]
    sub_chk = CheckpointRecord(
        run_id="run-sub-map",
        stage_name="stg_map",
        step_name="m_sub_res[0]",
        status=StepStatus.COMPLETED,
        output_payload=999,
        started_at=now,
        completed_at=now,
    )
    store.save_checkpoint(sub_chk)

    called_items: list[int] = []

    def track_action(x: int) -> int:
        called_items.append(x)
        return x * 10

    step_sub_res = StepDefinition(
        name="m_sub_res", action=track_action, is_mapped=True, map_over="items"
    )
    res_sub = await engine._execute_mapped_step(
        state=state,
        stage=stage,
        step=step_sub_res,
        cached_outputs={},
        initial_inputs={},
        step_inputs={"items": [10, 20]},
    )
    # Item 0 was loaded from checkpoint (999), Item 1 was executed (200)
    assert res_sub == [999, 200]
    assert called_items == [20]

    # 2. Direct _execute_mapped_sub_step returns output
    res_single = await engine._execute_mapped_sub_step(
        state=state,
        stage_name="stg_map",
        step=step_sub_res,
        step_inputs={"items": [10, 20]},
        idx=2,
        item_val=50,
    )
    assert res_single == 500

    # 3. Custom remote_executor to verify partition.node_id is node-{idx % 4}
    dispatched_nodes: list[tuple[int, str]] = []

    def record_rpc(run_id: str, step_name: str, part: Any, payload: Any) -> Any:
        dispatched_nodes.append((part.partition_id, part.node_id))
        return payload

    engine._barrier = GrpcSplitJoinBarrierAdapter(remote_executor=record_rpc)
    await engine._execute_mapped_sub_step(
        state=state,
        stage_name="stg_map",
        step=step_sub_res,
        step_inputs={"items": [10, 20]},
        idx=3,
        item_val=77,
    )
    assert dispatched_nodes[-1] == (3, "node-3")

    # 4. Verify node_id modulo in _execute_mapped_step barrier dispatch
    captured_dispatched: list[Any] = []

    async def fake_await_barrier(
        run_id: str,
        step_name: str,
        partitions: list[BarrierPartition],
        timeout_seconds: float | None = None,
    ) -> BarrierResolutionSummary:
        captured_dispatched.extend(partitions)
        return BarrierResolutionSummary(
            step_name=step_name,
            total_partitions=len(partitions),
            completed_partitions=len(partitions),
            failed_partitions=0,
            state=BarrierState.RESOLVED,
            outputs=[p.payload for p in partitions],
            duration_seconds=0.1,
        )

    monkeypatch.setattr(engine._barrier, "await_barrier", fake_await_barrier)
    await engine._execute_mapped_step(
        state=state,
        stage=stage,
        step=StepDefinition(
            name="m_nodes", action=lambda x: x, is_mapped=True, map_over="items"
        ),
        cached_outputs={},
        initial_inputs={},
        step_inputs={"items": [1, 2, 3]},
    )
    assert [p.node_id for p in captured_dispatched] == ["node-0", "node-1", "node-2"]


def test_distributed_engine_default_storage_fallback() -> None:
    """Verify DistributedWorkflowEngine initializes InMemoryStorage when storage=None."""
    engine = HexaqueueDistributedEngine(storage=None, staging=None)
    staging = engine._staging
    assert isinstance(staging, StoragePortArtifactStagingAdapter)
    assert isinstance(staging._storage, InMemoryStorage)


@pytest.mark.asyncio
async def test_execute_workflow_resumption_and_restart_cached_outputs(
    test_setup: tuple[Any, Any, Any],
) -> None:
    """Verify that resumption populates cached_outputs only for COMPLETED checkpoints and restart does not."""
    engine, storage, store = test_setup
    run_id = "test-cached-outputs-run"
    now = datetime.now(UTC)

    # Save existing checkpoints from a previous run
    chk_completed = CheckpointRecord(
        run_id=run_id,
        stage_name="s0",
        step_name="step_prior",
        status=StepStatus.COMPLETED,
        attempt_number=1,
        input_payload={},
        output_payload="payload_from_prior",
        started_at=now,
        completed_at=now,
        duration_seconds=0.1,
    )
    chk_failed = CheckpointRecord(
        run_id=run_id,
        stage_name="s0",
        step_name="step_failed_prior",
        status=StepStatus.FAILED,
        attempt_number=1,
        input_payload={},
        output_payload="bad_payload",
        started_at=now,
        completed_at=now,
        duration_seconds=0.1,
    )
    store.save_checkpoint(chk_completed)
    store.save_checkpoint(chk_failed)

    state = WorkflowExecutionState(
        run_id=run_id,
        workflow_name="wf_cached",
        status=WorkflowStatus.RUNNING,
    )
    store.save_run(state)

    wf = WorkflowDefinition(
        name="wf_cached",
        stages=[
            StageDefinition(
                name="stage_dummy",
                steps=[
                    StepDefinition(name="step_dummy", action=lambda: "dummy_out"),
                ],
            ),
        ],
    )

    captured_cached: dict[str, Any] = {}

    async def fake_execute_stage(
        state_arg: Any,
        stage_arg: Any,
        workflow_arg: Any,
        cached_outputs_arg: dict[str, Any],
        inputs_arg: Any,
        skipped_steps_arg: Any,
        is_restart: bool = False,
    ) -> None:
        captured_cached.update(cached_outputs_arg)

    # 1. Resumption path (is_restart=False): must load COMPLETED output and ignore FAILED
    with patch.object(engine, "_execute_stage", new=fake_execute_stage):
        state_res = WorkflowExecutionState(
            run_id=run_id,
            workflow_name="wf_cached",
            status=WorkflowStatus.RUNNING,
        )
        res_state = await engine._execute_workflow(state_res, wf, {}, is_restart=False)

    assert res_state.status == WorkflowStatus.COMPLETED
    assert captured_cached.get("step_prior") == "payload_from_prior"
    assert "step_failed_prior" not in captured_cached
    assert res_state.step_checkpoints["step_prior"] == chk_completed
    assert res_state.step_checkpoints["step_failed_prior"] == chk_failed

    # 2. Restart path (is_restart=True): must NOT populate prior checkpoints or cached outputs
    captured_cached.clear()
    with patch.object(engine, "_execute_stage", new=fake_execute_stage):
        state_re = WorkflowExecutionState(
            run_id=run_id,
            workflow_name="wf_cached",
            status=WorkflowStatus.RUNNING,
        )
        re_state = await engine._execute_workflow(state_re, wf, {}, is_restart=True)

    assert re_state.status == WorkflowStatus.COMPLETED
    assert captured_cached == {}
    assert "step_prior" not in re_state.step_checkpoints
    assert "step_failed_prior" not in re_state.step_checkpoints
