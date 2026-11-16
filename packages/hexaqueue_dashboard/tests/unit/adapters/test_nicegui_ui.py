"""Unit tests for NiceGUI dashboard UI mounting."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from hexastack_auth.domain.models import Identity
from nicegui import app as nicegui_app

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, JobStatus, TerminalOutcome
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_dashboard.adapters import nicegui_ui
from hexaqueue_dashboard.adapters.auth import DashboardAuthManager
from hexaqueue_dashboard.adapters.nicegui_ui import (
    _render_console_panel,
    _render_jobs_section,
    _render_login_panel,
    _resolve_session_identity,
    mount_dashboard_ui,
)
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.domain.models import RunSubmission
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


def test_mount_dashboard_ui_registers_nicegui_and_auth_manager() -> None:
    """Verify mount_dashboard_ui attaches auth_manager and NiceGUI routes."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    app = FastAPI()
    manager = DashboardAuthManager(jwt_secret="test-secret-for-nicegui-mount-32bytes")

    mount_dashboard_ui(app, pipeline, auth_manager=manager, mount_path="/dashboard/ui")

    bound_manager = getattr(app.state, "auth_manager", None)
    assert bound_manager is manager
    route_paths = {getattr(r, "path", "") for r in nicegui_app.routes}
    has_ui_route = "/dashboard/ui" in route_paths
    assert has_ui_route is True


class _FakeElement:
    def __init__(self, value: str = "") -> None:
        self.value = value
        self.text = ""

    def __enter__(self) -> _FakeElement:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def classes(self, *_args: object, **_kwargs: object) -> _FakeElement:
        return self

    def props(self, *_args: object, **_kwargs: object) -> _FakeElement:
        return self

    def tooltip(self, *_args: object, **_kwargs: object) -> _FakeElement:
        return self

    def add_slot(self, *_args: object, **_kwargs: object) -> None:
        return None

    def on(self, event_name: str, handler: Any) -> None:
        return None

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_nicegui_ui_identity_and_panels(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify NiceGUI identity resolution, login panel, and console rendering."""
    fake_storage = SimpleNamespace(user={})
    monkeypatch.setattr(nicegui_ui.nicegui_app, "storage", fake_storage)

    def _fake_refreshable(fn):  # type: ignore[no-untyped-def]
        fn.refresh = lambda: None
        return fn

    captured_buttons: dict[str, Any] = {}
    captured_timers: list[Any] = []
    captured_on_changes: list[Any] = []
    js_calls: list[str] = []

    def _fake_button(label: str = "", *args: object, **kwargs: Any) -> _FakeElement:
        if "on_click" in kwargs:
            captured_buttons[label] = kwargs["on_click"]
        return _FakeElement()

    def _fake_input(*_args: object, **kwargs: Any) -> _FakeElement:
        if "on_change" in kwargs:
            captured_on_changes.append(kwargs["on_change"])
        return _FakeElement()

    def _fake_timer(_interval: float, callback: Any) -> None:
        captured_timers.append(callback)

    fake_ui = SimpleNamespace(
        card=lambda *_a, **_k: _FakeElement(),
        row=lambda *_a, **_k: _FakeElement(),
        column=lambda *_a, **_k: _FakeElement(),
        label=lambda *_a, **_k: _FakeElement(),
        input=_fake_input,
        select=_fake_input,
        table=lambda *_a, **_k: _FakeElement(),
        tree=lambda *_a, **_k: _FakeElement(),
        dialog=lambda *_a, **_k: _FakeElement(),
        button=_fake_button,
        separator=lambda *_a, **_k: _FakeElement(),
        notify=lambda *_a, **_k: None,
        navigate=SimpleNamespace(reload=lambda: None),
        header=lambda *_a, **_k: _FakeElement(),
        html=lambda *_a, **_k: _FakeElement(),
        add_body_html=lambda *_a, **_k: None,
        refreshable=_fake_refreshable,
        timer=_fake_timer,
        run_javascript=lambda code, *_a, **_k: js_calls.append(str(code)),
    )
    monkeypatch.setattr(nicegui_ui, "ui", fake_ui)

    manager = DashboardAuthManager(jwt_secret="test-secret-for-nicegui-mount-32bytes")
    assert _resolve_session_identity(manager) is None

    fake_storage.user["jwt"] = "not-a-valid-jwt"
    assert _resolve_session_identity(manager) is None

    ident = Identity(user_id="rjdw", roles=frozenset({"admin"}))
    fake_storage.user["jwt"] = manager.issue_token(ident)
    resolved = _resolve_session_identity(manager)
    assert resolved is not None
    assert resolved.user_id == "rjdw"

    _render_login_panel(manager)

    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    await _render_jobs_section(pipeline, ident)
    await _render_console_panel(pipeline, ident)

    # Exercise search & status filter callbacks
    for on_change_cb in captured_on_changes:
        on_change_cb(SimpleNamespace(value=""))

    # Exercise reactive refresh, timer tick, and sign-out callbacks
    refresh_cb = captured_buttons["Refresh"]
    await refresh_cb()
    timer_cb = captured_timers[0]
    await timer_cb()
    js_count = len(js_calls)
    assert js_count >= 2
    assert "changed: true" in js_calls[0]
    assert "changed: false" in js_calls[1]

    logout_cb = captured_buttons["Sign Out"]
    logout_cb()
    jwt_after_logout = fake_storage.user.get("jwt")
    assert jwt_after_logout is None


@pytest.mark.asyncio
async def test_jobs_table_filtering_badges_and_lifecycle_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify job row building, filtering, status badges, and hold/release/cancel dispatch."""
    fake_ui = SimpleNamespace(
        notify=lambda *_a, **_k: None,
        navigate=SimpleNamespace(reload=lambda: None),
    )
    monkeypatch.setattr(nicegui_ui, "ui", fake_ui)

    pending_job = JobSpec(
        id="j-pend",
        run_id="r-1",
        name="pending-task",
        command="echo 1",
        status=JobStatus(state=JobState.PENDING),
    )
    held_job = JobSpec(
        id="j-held",
        run_id="r-1",
        name="held-task",
        command="echo 2",
        status=JobStatus(state=JobState.BLOCKED, reason="Administratively held"),
    )
    done_job = JobSpec(
        id="j-done",
        run_id="r-2",
        name="done-task",
        command="echo 3",
        status=JobStatus(state=JobState.DONE, outcome=TerminalOutcome.COMPLETED),
    )

    assert nicegui_ui._resolve_display_status(pending_job) == "PENDING"
    assert nicegui_ui._resolve_display_status(held_job) == "HELD"
    assert nicegui_ui._resolve_display_status(done_job) == "COMPLETED"

    filtered_held = nicegui_ui._filter_jobs(
        [pending_job, held_job, done_job], status_filter="HELD"
    )
    assert [j.id for j in filtered_held] == ["j-held"]

    filtered_search = nicegui_ui._filter_jobs(
        [pending_job, held_job, done_job], search_text="r-2"
    )
    assert [j.id for j in filtered_search] == ["j-done"]

    rows = nicegui_ui._build_job_rows([pending_job, held_job, done_job])
    assert rows[0]["can_hold"] is True
    assert rows[0]["can_release"] is False
    assert rows[1]["can_release"] is True
    assert rows[2]["can_cancel"] is False

    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    await controller.submit_run(
        RunSubmission(run_spec=RunSpec(id="r-1", name="run-1"), jobs=[pending_job])
    )
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    ident = Identity(user_id="rjdw", roles=frozenset({"admin"}))

    await nicegui_ui._dispatch_lifecycle_action(pipeline, ident, "hold", "j-pend")
    held_state = (await controller.get_job("j-pend")).state
    assert held_state == JobState.BLOCKED

    await nicegui_ui._dispatch_lifecycle_action(pipeline, ident, "release", "j-pend")
    released_state = (await controller.get_job("j-pend")).state
    assert released_state == JobState.PENDING

    await nicegui_ui._dispatch_lifecycle_action(pipeline, ident, "cancel_run", "r-1")
    cancelled_outcome = (await controller.get_job("j-pend")).outcome
    assert cancelled_outcome == TerminalOutcome.CANCELLED

    # Exercise _render_jobs_section table slots, event handlers, cancel_job, and dialog
    table_events: dict[str, Any] = {}
    dialog_buttons: dict[str, Any] = {}

    class _FakeTable(_FakeElement):
        def on(self, event_name: str, handler: Any) -> None:
            table_events[event_name] = handler

    def _fake_dialog_btn(label: str = "", *_a: object, **kwargs: Any) -> _FakeElement:
        if "on_click" in kwargs:
            dialog_buttons[label] = kwargs["on_click"]
        return _FakeElement()

    rich_ui = SimpleNamespace(
        label=lambda *_a, **_k: _FakeElement(),
        row=lambda *_a, **_k: _FakeElement(),
        card=lambda *_a, **_k: _FakeElement(),
        table=lambda *_a, **_k: _FakeTable(),
        dialog=lambda *_a, **_k: _FakeElement(),
        button=_fake_dialog_btn,
        notify=lambda *_a, **_k: None,
        navigate=SimpleNamespace(reload=lambda: None),
    )
    monkeypatch.setattr(nicegui_ui, "ui", rich_ui)

    mutated_calls = 0

    async def _on_mutated() -> None:
        nonlocal mutated_calls
        mutated_calls += 1

    await _render_jobs_section(
        pipeline, ident, jobs=[pending_job], on_mutated=_on_mutated
    )
    await table_events["hold_job"](SimpleNamespace(args={"job_id": "j-pend"}))
    await table_events["release_job"](SimpleNamespace(args={"job_id": "j-pend"}))
    await table_events["cancel_job"](SimpleNamespace(args={"job_id": "j-pend"}))
    table_events["cancel_run"](SimpleNamespace(args={"run_id": "r-1"}))
    await dialog_buttons["Confirm Cancel Run"]()
    assert mutated_calls == 4

    # Error path in _dispatch_lifecycle_action
    await nicegui_ui._dispatch_lifecycle_action(
        pipeline, ident, "cancel_job", "nonexistent-job"
    )

    # Verify nested DAG tree builder and _render_runs_section
    child_job = JobSpec(
        id="j-child",
        run_id="r-1",
        name="child-task",
        command="echo child",
        status=JobStatus(state=JobState.PENDING),
    )
    await controller.submit_run(
        RunSubmission(
            run_spec=RunSpec(id="r-dag", name="nested-dag"),
            jobs=[
                pending_job.model_copy(update={"id": "j-root", "run_id": "r-dag"}),
                child_job.model_copy(update={"run_id": "r-dag"}),
            ],
            dependencies={"j-child": ["j-root"]},
        )
    )
    runs_list = await controller.list_runs()
    dag_jobs = await controller.list_jobs()
    tree_nodes = nicegui_ui._build_run_tree_nodes(runs_list, dag_jobs)
    dag_node = next(n for n in tree_nodes if n["run_id"] == "r-dag")
    children = dag_node["children"]
    assert isinstance(children, list)
    assert children[0]["job_id"] == "j-root"
    assert children[0]["children"][0]["job_id"] == "j-child"

    # Verify job and run inspection drawers (logs, explainability, DAG links, callbacks)
    drawer_buttons: dict[str, Any] = {}
    tree_select_cbs: list[Any] = []

    def _capture_drawer_btn(
        label: str = "", *_a: object, **kwargs: Any
    ) -> _FakeElement:
        if "on_click" in kwargs:
            drawer_buttons[label] = kwargs["on_click"]
        return _FakeElement()

    def _capture_tree(*_a: object, **kwargs: Any) -> _FakeElement:
        if "on_select" in kwargs:
            tree_select_cbs.append(kwargs["on_select"])
        return _FakeElement()

    drawer_ui = SimpleNamespace(
        label=lambda *_a, **_k: _FakeElement(),
        tree=_capture_tree,
        row=lambda *_a, **_k: _FakeElement(),
        card=lambda *_a, **_k: _FakeElement(),
        dialog=lambda *_a, **_k: _FakeElement(),
        button=_capture_drawer_btn,
        html=lambda *_a, **_k: _FakeElement(),
        notify=lambda *_a, **_k: None,
        navigate=SimpleNamespace(reload=lambda: None),
    )
    monkeypatch.setattr(nicegui_ui, "ui", drawer_ui)
    nicegui_ui._render_runs_section(pipeline, ident, runs_list, dag_jobs)

    run_report = next(r for r in runs_list if r.run_id == "r-dag")
    root_job = next(j for j in dag_jobs if j.id == "j-root")
    child_dag_job = next(j for j in dag_jobs if j.id == "j-child")
    filtered_runs: list[str] = []

    await nicegui_ui._open_job_inspection_drawer(
        pipeline,
        ident,
        child_dag_job,
        run_report=run_report,
        all_jobs=dag_jobs,
        on_mutated=_on_mutated,
        on_filter_run=filtered_runs.append,
    )
    drawer_buttons["Filter Table to Run"]()
    assert filtered_runs == ["r-dag"]
    await drawer_buttons["Parent: j-root"]()
    await drawer_buttons["Child: j-child"]()
    await drawer_buttons["Inspect Run"]()

    await nicegui_ui._open_run_inspection_drawer(
        pipeline,
        ident,
        run_report,
        dag_jobs,
        on_mutated=_on_mutated,
        on_filter_run=filtered_runs.append,
    )
    drawer_buttons["Filter Jobs Table to Run"]()
    drawer_buttons["Cancel Run"]()
    await tree_select_cbs[0](SimpleNamespace(value="run:r-dag"))
    await tree_select_cbs[0](SimpleNamespace(value="job:j-root"))

    nicegui_ui._render_drawer_explain_and_logs(
        None,
        "err",
        [LogChunk(job_id="j-root", offset=0, stream="stdout", content="hello")],
        None,
    )
    nicegui_ui._render_drawer_explain_and_logs(None, "err", [], "no logs")
    await nicegui_ui._open_job_inspection_drawer(
        pipeline,
        ident,
        root_job,
        run_report=run_report,
        all_jobs=dag_jobs,
    )
