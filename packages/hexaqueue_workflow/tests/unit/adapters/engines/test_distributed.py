"""Tests for HexaqueueDistributedEngine."""

import asyncio
from typing import Any
from unittest.mock import MagicMock

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
    StepContext,
    StepStatus,
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
from hexaqueue_workflow.adapters.engines.distributed import (
    HexaqueueDistributedEngine,
)
from hexaqueue_workflow.adapters.staging.storage import (
    StoragePortArtifactStagingAdapter,
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
