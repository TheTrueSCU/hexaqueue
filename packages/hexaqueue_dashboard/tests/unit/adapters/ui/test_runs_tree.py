"""Unit tests for expandable Runs & nested DAG tree view."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from hexastack_auth.domain.models import Identity

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, JobStatus
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_dashboard.adapters.ui import inspection_drawer as drawer_mod
from hexaqueue_dashboard.adapters.ui import runs_tree as runs_mod
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.domain.models import RunSubmission
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


class _FakeEl:
    def __enter__(self) -> _FakeEl:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def classes(self, *_args: object) -> _FakeEl:
        return self

    def props(self, *_args: object) -> _FakeEl:
        return self

    def add_slot(self, *_args: object, **_kwargs: object) -> None:
        return None

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_runs_tree_builder_and_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify nested DAG tree construction and node selection drawer dispatch."""
    select_cbs: list[Any] = []

    def _cap_tree(*_a: object, **kwargs: Any) -> _FakeEl:
        if "on_select" in kwargs:
            select_cbs.append(kwargs["on_select"])
        return _FakeEl()

    fake_ui = SimpleNamespace(
        label=lambda *_a, **_k: _FakeEl(),
        tree=_cap_tree,
        dialog=lambda *_a, **_k: _FakeEl(),
        card=lambda *_a, **_k: _FakeEl(),
        row=lambda *_a, **_k: _FakeEl(),
        button=lambda *_a, **_k: _FakeEl(),
        html=lambda *_a, **_k: _FakeEl(),
        notify=lambda *_a, **_k: None,
        navigate=SimpleNamespace(reload=lambda: None),
    )
    monkeypatch.setattr(runs_mod, "ui", fake_ui)
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

    runs_mod.render_runs_section(pipeline, ident, runs_list, dag_jobs)
    await select_cbs[0](SimpleNamespace(value="run:r-dag"))
    await select_cbs[0](SimpleNamespace(value="job:j-root"))
