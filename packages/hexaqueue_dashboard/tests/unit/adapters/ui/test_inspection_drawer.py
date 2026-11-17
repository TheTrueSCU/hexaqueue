"""Unit tests for the unified slide-over inspection drawer and lifecycle actions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from hexastack_auth.domain.models import Identity

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, JobStatus, TerminalOutcome
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_dashboard.adapters.ui import inspection_drawer as drawer_mod
from hexaqueue_dashboard.adapters.ui.state import DrawerUIState
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.domain.models import RunSubmission
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


@pytest.mark.asyncio
async def test_inspection_drawer_and_lifecycle_actions(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: Any,
) -> None:
    """Verify job/run drawers, DAG navigation links, logs, and lifecycle dispatch."""
    buttons: dict[str, Any] = {}

    def _cap_btn(label: str = "", *_a: object, **kwargs: Any) -> Any:
        if "on_click" in kwargs:
            buttons[label] = kwargs["on_click"]
        return fake_el()

    fake_ui = SimpleNamespace(
        dialog=lambda *_a, **_k: fake_el(),
        card=lambda *_a, **_k: fake_el(),
        row=lambda *_a, **_k: fake_el(),
        column=lambda *_a, **_k: fake_el(),
        label=lambda *_a, **_k: fake_el(),
        button=_cap_btn,
        html=lambda *_a, **_k: fake_el(),
        notify=lambda *_a, **_k: None,
        navigate=SimpleNamespace(reload=lambda: None),
    )
    monkeypatch.setattr(drawer_mod, "ui", fake_ui)

    root_job = JobSpec(
        id="j-root",
        run_id="r-dag",
        name="root",
        command="echo root",
        status=JobStatus(state=JobState.PENDING),
    )
    child_job = JobSpec(
        id="j-child",
        run_id="r-dag",
        name="child",
        command="echo child",
        status=JobStatus(state=JobState.PENDING),
    )
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    run_report = await controller.submit_run(
        RunSubmission(
            run_spec=RunSpec(id="r-dag", name="nested-dag"),
            jobs=[root_job, child_job],
            dependencies={"j-child": ["j-root"]},
        )
    )
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    ident = Identity(user_id="rjdw", roles=frozenset({"admin"}))
    all_jobs = await controller.list_jobs()
    filtered_runs: list[str] = []

    await drawer_mod.open_job_inspection_drawer(
        pipeline,
        ident,
        child_job,
        run_report=run_report,
        all_jobs=all_jobs,
        on_filter_run=filtered_runs.append,
    )
    buttons["Filter Table to Run"]()
    assert filtered_runs == ["r-dag"]
    await buttons["Parent: j-root"]()
    await buttons["Child: j-child"]()
    await buttons["Inspect Run"]()
    buttons["Filter Jobs Table to Run"]()
    buttons["Cancel Run"]()
    await buttons["Confirm Cancel Run"]()

    cancelled_state = (await controller.get_job("j-root")).outcome
    assert cancelled_state == TerminalOutcome.CANCELLED

    drawer_mod.render_drawer_explain_and_logs(
        None,
        "err",
        [LogChunk(job_id="j-root", offset=0, stream="stdout", content="hello")],
        None,
    )
    drawer_mod.render_drawer_explain_and_logs(None, "err", [], "no logs")


@pytest.mark.asyncio
async def test_running_job_hides_explainability_and_completed_run_hides_cancel(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: Any,
) -> None:
    """Verify running jobs show State Timeline without Explainability, and finished runs hide Cancel Run."""
    labels: list[str] = []
    buttons: dict[str, Any] = {}

    def _cap_label(text: str = "", *_a: object, **_k: object) -> Any:
        labels.append(str(text))
        return fake_el()

    def _cap_btn(label: str = "", *_a: object, **kwargs: Any) -> Any:
        if "on_click" in kwargs:
            buttons[label] = kwargs["on_click"]
        return fake_el()

    fake_ui = SimpleNamespace(
        dialog=lambda *_a, **_k: fake_el(),
        card=lambda *_a, **_k: fake_el(),
        row=lambda *_a, **_k: fake_el(),
        column=lambda *_a, **_k: fake_el(),
        label=_cap_label,
        button=_cap_btn,
        html=lambda *_a, **_k: fake_el(),
        notify=lambda *_a, **_k: None,
        navigate=SimpleNamespace(reload=lambda: None),
    )
    monkeypatch.setattr(drawer_mod, "ui", fake_ui)

    running_job = JobSpec(
        id="j-run",
        run_id="r-done",
        name="running-job",
        command="echo running",
        status=JobStatus(state=JobState.RUNNING, reason="dispatched"),
        assigned_worker_id="worker-1",
    )
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    run_report = await controller.submit_run(
        RunSubmission(
            run_spec=RunSpec(id="r-done", name="finished-run"),
            jobs=[running_job],
        )
    )
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    ident = Identity(user_id="rjdw", roles=frozenset({"admin"}))

    await drawer_mod.open_job_inspection_drawer(pipeline, ident, running_job)
    has_timeline = "State Timeline" in labels
    has_explain = "Scheduler Explainability" in labels
    has_worker_entry = any("worker-1" in lbl for lbl in labels)
    assert has_timeline is True
    assert has_explain is False
    assert has_worker_entry is True

    buttons.clear()
    finished_report = run_report.model_copy(
        update={"pending_jobs": 0, "running_jobs": 0, "completed_jobs": 1}
    )
    await drawer_mod.open_run_inspection_drawer(
        pipeline, ident, finished_report, [running_job]
    )
    has_cancel_run = "Cancel Run" in buttons
    has_run_log = "Run Event Log" in labels
    assert has_cancel_run is False
    assert has_run_log is True

    # Exercise live in-place drawer refresh for both job and run drawers
    html_calls: list[str] = []
    fake_ui.html = lambda markup, **_k: html_calls.append(str(markup)) or fake_el()
    drawer_state = DrawerUIState(host=fake_el())
    pending_job = running_job.model_copy(
        update={"status": JobStatus(state=JobState.PENDING)}
    )
    await drawer_mod.open_job_inspection_drawer(
        pipeline, ident, pending_job, drawer_state=drawer_state
    )
    assert drawer_state.active is not None
    await drawer_mod.refresh_active_drawer(
        pipeline, ident, drawer_state, [running_job], [finished_report]
    )
    has_running_badge = any("RUNNING" in h for h in html_calls)
    assert has_running_badge is True

    await drawer_mod.open_run_inspection_drawer(
        pipeline, ident, finished_report, [running_job], drawer_state=drawer_state
    )
    await drawer_mod.refresh_active_drawer(
        pipeline, ident, drawer_state, [running_job], [finished_report]
    )
