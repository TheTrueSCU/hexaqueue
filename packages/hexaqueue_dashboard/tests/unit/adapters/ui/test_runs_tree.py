"""Unit tests for expandable Runs & nested DAG tree view."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from hexastack_auth.domain.models import Identity

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, JobStatus, RunState
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_dashboard.adapters.ui import inspection_drawer as drawer_mod
from hexaqueue_dashboard.adapters.ui import logs_view as logs_mod
from hexaqueue_dashboard.adapters.ui import runs_tree as runs_mod
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


@pytest.mark.asyncio
async def test_runs_tree_builder_and_selection(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: Any,
) -> None:
    """Verify nested DAG tree construction and node selection drawer dispatch."""
    select_cbs: list[Any] = []

    def _cap_tree(*_a: object, **kwargs: Any) -> Any:
        if "on_select" in kwargs:
            select_cbs.append(kwargs["on_select"])
        return fake_el()

    fake_ui = SimpleNamespace(
        label=lambda *_a, **_k: fake_el(),
        tree=_cap_tree,
        dialog=lambda *_a, **_k: fake_el(),
        card=lambda *_a, **_k: fake_el(),
        row=lambda *_a, **_k: fake_el(),
        column=lambda *_a, **_k: fake_el(),
        button=lambda *_a, **_k: fake_el(),
        html=lambda *_a, **_k: fake_el(),
        notify=lambda *_a, **_k: None,
        navigate=SimpleNamespace(reload=lambda: None, to=lambda *_a, **_k: None),
        switch=lambda *_a, **_k: fake_el(),
        timer=lambda *_a, **_k: fake_el(),
    )
    monkeypatch.setattr(runs_mod, "ui", fake_ui)
    monkeypatch.setattr(drawer_mod, "ui", fake_ui)
    monkeypatch.setattr(logs_mod, "ui", fake_ui)

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
    await controller.submit_run(
        RunSubmission(
            run_spec=RunSpec(id="r-dag", name="nested-dag"),
            jobs=[root_job, child_job],
            dependencies={"j-child": ["j-root"]},
        )
    )
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    ident = Identity(user_id="rjdw", roles=frozenset({"admin"}))

    runs_list = await controller.list_runs()
    dag_jobs = await controller.list_jobs()
    nodes = runs_mod.build_run_tree_nodes(runs_list, dag_jobs)
    assert len(nodes) == 1
    children = nodes[0]["children"]
    assert isinstance(children, list)
    assert children[0]["job_id"] == "j-root"
    assert children[0]["children"][0]["job_id"] == "j-child"

    expanded: set[str] = {"run:r-dag"}
    runs_mod.render_runs_section(
        pipeline, ident, runs_list, dag_jobs, expanded_nodes=expanded
    )
    await select_cbs[0](SimpleNamespace(value="run:r-dag"))
    await select_cbs[0](SimpleNamespace(value="job:j-root"))


def test_render_runs_section_orders_newest_to_oldest(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: Any,
) -> None:
    """Verify render_runs_section displays runs newest-to-oldest regardless of input order."""
    captured_nodes: list[list[dict[str, Any]]] = []

    def _cap_tree(nodes: list[dict[str, Any]], **_k: Any) -> Any:
        captured_nodes.append(nodes)
        return fake_el()

    fake_ui = SimpleNamespace(
        label=lambda *_a, **_k: fake_el(),
        tree=_cap_tree,
        button=lambda *_a, **_k: fake_el(),
    )
    monkeypatch.setattr(runs_mod, "ui", fake_ui)

    t0 = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
    r_old = RunStatusReport(
        run_id="r-old",
        state=RunState.DONE,
        total_jobs=1,
        completed_jobs=1,
        failed_jobs=0,
        running_jobs=0,
        pending_jobs=0,
        created_at=t0,
    )
    r_mid = RunStatusReport(
        run_id="r-mid",
        state=RunState.DONE,
        total_jobs=1,
        completed_jobs=1,
        failed_jobs=0,
        running_jobs=0,
        pending_jobs=0,
        created_at=t0 + timedelta(minutes=5),
    )
    r_new = RunStatusReport(
        run_id="r-new",
        state=RunState.RUNNING,
        total_jobs=1,
        completed_jobs=0,
        failed_jobs=0,
        running_jobs=1,
        pending_jobs=0,
        created_at=t0 + timedelta(minutes=10),
    )

    ident = Identity(user_id="rjdw", roles=frozenset({"admin"}))
    pipeline: Any = SimpleNamespace()
    runs_mod.render_runs_section(
        pipeline,
        ident,
        [r_old, r_new, r_mid],
        [],
        show_heading=False,
    )

    rendered_ids = [n["id"] for n in captured_nodes[0]]
    assert rendered_ids == ["run:r-new", "run:r-mid", "run:r-old"]
