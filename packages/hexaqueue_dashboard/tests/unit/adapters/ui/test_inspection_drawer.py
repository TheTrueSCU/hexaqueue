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

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_inspection_drawer_and_lifecycle_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify job/run drawers, DAG navigation links, logs, and lifecycle dispatch."""
    buttons: dict[str, Any] = {}

    def _cap_btn(label: str = "", *_a: object, **kwargs: Any) -> _FakeEl:
        if "on_click" in kwargs:
            buttons[label] = kwargs["on_click"]
        return _FakeEl()

    fake_ui = SimpleNamespace(
        dialog=lambda *_a, **_k: _FakeEl(),
        card=lambda *_a, **_k: _FakeEl(),
        row=lambda *_a, **_k: _FakeEl(),
        label=lambda *_a, **_k: _FakeEl(),
        button=_cap_btn,
        html=lambda *_a, **_k: _FakeEl(),
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
