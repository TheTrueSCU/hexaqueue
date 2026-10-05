"""Unit tests for NotificationDispatcher in hexaqueue_core.infra."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from hexastack_core.ports.notification import (
    NotificationPort,
    NotificationPriority,
)

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import (
    JobState,
    JobStatus,
    TerminalOutcome,
)
from hexaqueue_core.domain.notification import (
    NotificationPolicy,
    NotificationTrigger,
)
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.infra.notification import NotificationDispatcher


def test_dispatcher_disabled_when_port_is_none() -> None:
    """Verify dispatcher acts as a safe no-op when notification_port is None."""
    dispatcher = NotificationDispatcher(notification_port=None)
    res_enabled = dispatcher.is_enabled
    assert res_enabled is False

    job = JobSpec(
        id="job-1",
        run_id="run-1",
        name="test-task",
        command="echo hello",
    )
    res_job = dispatcher.dispatch_job_event(job, NotificationTrigger.FAILED)
    assert res_job == []

    run = RunSpec(id="run-1", name="test-run", jobs=[job])
    res_run = dispatcher.dispatch_run_event(run, NotificationTrigger.COMPLETED)
    assert res_run == []

    res_step = dispatcher.dispatch_step_event(
        "wf-1", "step-1", NotificationTrigger.STARTED
    )
    assert res_step == []


def test_dispatcher_job_event_delivery_and_escalation() -> None:
    """Verify job event policy matching, target registration, and priority escalation."""
    mock_port = MagicMock(spec=NotificationPort)
    mock_port.notify.return_value = True
    mock_port.add_url = MagicMock()

    policy = NotificationPolicy(
        targets=["slack://channel-a"],
        triggers=NotificationTrigger.ERRORS,
        priority=NotificationPriority.NORMAL,
        escalate_on_error=True,
        tags=["ci"],
    )

    job = JobSpec(
        id="job-42",
        run_id="run-99",
        name="compile-bin",
        command="make all",
        notifications=[policy],
        status=JobStatus(
            state=JobState.DONE,
            outcome=TerminalOutcome.FAILED,
            reason="Segmentation fault",
        ),
    )

    dispatcher = NotificationDispatcher(notification_port=mock_port)
    assert dispatcher.is_enabled is True

    # 1. Non-matching trigger: STARTED
    res_started = dispatcher.dispatch_job_event(job, NotificationTrigger.STARTED)
    assert res_started == []
    assert mock_port.notify.call_count == 0

    # 2. Matching trigger: FAILED
    res_failed = dispatcher.dispatch_job_event(
        job,
        NotificationTrigger.FAILED,
        details={"exit_code": 139, "node_id": "worker-node-3"},
    )
    assert res_failed == [True]
    mock_port.add_url.assert_not_called()
    assert mock_port.notify.call_count == 1

    call_args = mock_port.notify.call_args.kwargs
    assert call_args["title"] == "[Hexaqueue] Job compile-bin (job-42): FAILED"
    assert "**Exit Code:** `139`" in call_args["body"]
    assert "**Node:** `worker-node-3`" in call_args["body"]
    assert "Segmentation fault" in call_args["body"]
    assert call_args["priority"] == NotificationPriority.HIGH
    assert call_args["targets"] == ["slack://channel-a"]
    assert "failed" in call_args["tags"]
    assert "ci" in call_args["tags"]


def test_dispatcher_legacy_adapter_fallback() -> None:
    """Verify fallback to add_url when NotificationPort does not accept targets."""

    class LegacyPort(NotificationPort):
        def __init__(self) -> None:
            self.urls: list[str] = []
            self.calls: list[dict[str, Any]] = []

        def add_url(self, url: str) -> None:
            self.urls.append(url)

        def notify(
            self,
            title: str,
            body: str,
            priority: NotificationPriority = NotificationPriority.NORMAL,
            tags: list[str] | None = None,
        ) -> bool:
            self.calls.append(
                {"title": title, "body": body, "priority": priority, "tags": tags}
            )
            return True

    legacy = LegacyPort()
    dispatcher = NotificationDispatcher(notification_port=legacy)
    policy = NotificationPolicy(
        targets=["discord://webhook-1"],
        triggers=NotificationTrigger.COMPLETED,
    )
    job = JobSpec(
        id="j1",
        run_id="r1",
        name="legacy-test",
        command="ls",
        notifications=[policy],
    )

    res = dispatcher.dispatch_job_event(job, NotificationTrigger.COMPLETED)
    assert res == [True]
    assert legacy.urls == ["discord://webhook-1"]
    assert len(legacy.calls) == 1
    assert legacy.calls[0]["title"] == "[Hexaqueue] Job legacy-test (j1): COMPLETED"


def test_dispatcher_job_event_custom_template() -> None:
    """Verify custom message formatting template interpolation."""
    mock_port = MagicMock(spec=NotificationPort)
    mock_port.notify.return_value = True

    policy = NotificationPolicy(
        triggers=NotificationTrigger.COMPLETED,
        template="Job {job.name} finished with trigger {trigger.name}! Node: {node}",
    )
    job = JobSpec(
        id="job-10",
        run_id="run-1",
        name="test-runner",
        command="pytest",
        notifications=[policy],
    )

    dispatcher = NotificationDispatcher(notification_port=mock_port)
    res = dispatcher.dispatch_job_event(
        job,
        NotificationTrigger.COMPLETED,
        details={"node": "gpu-node-1"},
    )
    assert res == [True]

    call_args = mock_port.notify.call_args.kwargs
    assert (
        call_args["body"]
        == "Job test-runner finished with trigger COMPLETED! Node: gpu-node-1"
    )


def test_dispatcher_run_event_delivery() -> None:
    """Verify run-level notification delivery with aggregate job stats."""
    mock_port = MagicMock(spec=NotificationPort)
    mock_port.notify.return_value = True

    policy = NotificationPolicy(
        triggers=NotificationTrigger.COMPLETED | NotificationTrigger.FAILED,
        priority=NotificationPriority.NORMAL,
        escalate_on_error=False,
    )
    job = JobSpec(id="job-1", run_id="run-1", name="task-1", command="echo 1")
    run = RunSpec(
        id="run-100",
        name="nightly-pipeline",
        jobs=[job],
        notifications=[policy],
    )

    dispatcher = NotificationDispatcher(notification_port=mock_port)
    res = dispatcher.dispatch_run_event(
        run,
        NotificationTrigger.COMPLETED,
        details={"completed_jobs": 10, "failed_jobs": 0, "duration_seconds": 45.2},
    )
    assert res == [True]

    call_args = mock_port.notify.call_args.kwargs
    assert call_args["title"] == "[Hexaqueue] Run nightly-pipeline (run-100): COMPLETED"
    assert "**Total Jobs:** 1" in call_args["body"]
    assert "**Completed Jobs:** 10" in call_args["body"]
    assert "**Duration:** 45.20s" in call_args["body"]
    assert call_args["priority"] == NotificationPriority.NORMAL


def test_dispatcher_step_event_delivery() -> None:
    """Verify step-level notification dispatching within workflows."""
    mock_port = MagicMock(spec=NotificationPort)
    mock_port.notify.return_value = True

    policy = NotificationPolicy(
        triggers=NotificationTrigger.FAILED,
        priority=NotificationPriority.HIGH,
    )

    dispatcher = NotificationDispatcher(notification_port=mock_port)
    res = dispatcher.dispatch_step_event(
        workflow_id="wf-preprocess",
        step_name="shard_dataset",
        trigger=NotificationTrigger.FAILED,
        policies=[policy],
        details={"error": "OutOfMemoryError", "duration_seconds": 12.3},
    )
    assert res == [True]

    call_args = mock_port.notify.call_args.kwargs
    assert (
        call_args["title"]
        == "[Hexaqueue] Workflow wf-preprocess Step shard_dataset: FAILED"
    )
    assert "**Error:** OutOfMemoryError" in call_args["body"]
    assert "**Duration:** 12.30s" in call_args["body"]


@pytest.mark.asyncio
async def test_dispatcher_async_offloading() -> None:
    """Verify async dispatching methods successfully offload to worker threads."""
    mock_port = MagicMock(spec=NotificationPort)
    mock_port.notify.return_value = True

    policy = NotificationPolicy(triggers=NotificationTrigger.ALL)
    job = JobSpec(
        id="j-1", run_id="r-1", name="j1", command="ls", notifications=[policy]
    )
    run = RunSpec(id="r-1", name="r1", jobs=[job], notifications=[policy])

    dispatcher = NotificationDispatcher(notification_port=mock_port)

    # Async job event
    res_job = await dispatcher.async_dispatch_job_event(
        job, NotificationTrigger.STARTED
    )
    assert res_job == [True]

    # Async run event
    res_run = await dispatcher.async_dispatch_run_event(
        run, NotificationTrigger.SUBMITTED
    )
    assert res_run == [True]

    # Async step event
    res_step = await dispatcher.async_dispatch_step_event(
        "wf-1", "step-1", NotificationTrigger.COMPLETED, [policy]
    )
    assert res_step == [True]

    # Async with no port
    no_port_disp = NotificationDispatcher(notification_port=None)
    res_none = await no_port_disp.async_dispatch_job_event(
        job, NotificationTrigger.STARTED
    )
    assert res_none == []
