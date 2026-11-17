"""Unit tests for sortable, filterable Jobs table and KPI helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from hexastack_auth.domain.models import Identity

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, JobStatus, TerminalOutcome
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_dashboard.adapters.ui import inspection_drawer as drawer_mod
from hexaqueue_dashboard.adapters.ui import jobs_table as jobs_mod
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.domain.models import RunSubmission
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


class _FakeTable:
    def __init__(self, events: dict[str, Any]) -> None:
        self._events = events

    def classes(self, *_args: object) -> _FakeTable:
        return self

    def props(self, *_args: object) -> _FakeTable:
        return self

    def add_slot(self, *_args: object, **_kwargs: object) -> None:
        return None

    def on(self, event_name: str, handler: Any) -> None:
        self._events[event_name] = handler


@pytest.mark.asyncio
async def test_jobs_table_filtering_kpis_and_events(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: Any,
) -> None:
    """Verify job filtering, KPI counts, row building, and table lifecycle events."""
    events: dict[str, Any] = {}
    dialog_btns: dict[str, Any] = {}

    def _cap_btn(label: str = "", *_a: object, **kwargs: Any) -> Any:
        if "on_click" in kwargs:
            dialog_btns[label] = kwargs["on_click"]
        return fake_el()

    fake_ui = SimpleNamespace(
        label=lambda *_a, **_k: fake_el(),
        table=lambda *_a, **_k: _FakeTable(events),
        dialog=lambda *_a, **_k: fake_el(),
        card=lambda *_a, **_k: fake_el(),
        row=lambda *_a, **_k: fake_el(),
        column=lambda *_a, **_k: fake_el(),
        button=_cap_btn,
        html=lambda *_a, **_k: fake_el(),
        notify=lambda *_a, **_k: None,
        navigate=SimpleNamespace(reload=lambda: None),
    )
    monkeypatch.setattr(jobs_mod, "ui", fake_ui)
    monkeypatch.setattr(drawer_mod, "ui", fake_ui)

    p_job = JobSpec(
        id="j-pend",
        run_id="r-1",
        name="pend",
        command="echo 1",
        status=JobStatus(state=JobState.PENDING),
    )
    r_job = JobSpec(
        id="j-run",
        run_id="r-2",
        name="run",
        command="echo 2",
        status=JobStatus(state=JobState.RUNNING),
    )
    d_job = JobSpec(
        id="j-done",
        run_id="r-2",
        name="done",
        command="echo 3",
        status=JobStatus(state=JobState.DONE, outcome=TerminalOutcome.COMPLETED),
    )

    kpis_all = jobs_mod.compute_filtered_kpi_counts([p_job, r_job, d_job])
    assert kpis_all == (3, 1, 1, False)
    kpis_r2 = jobs_mod.compute_filtered_kpi_counts(
        [p_job, r_job, d_job], search_text="r-2"
    )
    assert kpis_r2 == (2, 1, 0, True)

    rows = jobs_mod.build_job_rows([p_job, r_job, d_job])
    assert rows[0]["can_hold"] is True
    assert rows[2]["can_cancel"] is False
    r0_rank = rows[0]["status_rank"]
    r1_rank = rows[1]["status_rank"]
    r2_rank = rows[2]["status_rank"]
    assert isinstance(r0_rank, int)
    assert isinstance(r1_rank, int)
    assert isinstance(r2_rank, int)
    assert r1_rank < r0_rank < r2_rank

    sorted_asc = jobs_mod.sort_job_rows(rows, "status", False)
    assert [r["status"] for r in sorted_asc] == ["RUNNING", "PENDING", "COMPLETED"]
    sorted_desc = jobs_mod.sort_job_rows(rows, "status", True)
    assert [r["status"] for r in sorted_desc] == ["COMPLETED", "PENDING", "RUNNING"]

    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    await controller.submit_run(
        RunSubmission(run_spec=RunSpec(id="r-1", name="run-1"), jobs=[p_job])
    )
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    ident = Identity(user_id="rjdw", roles=frozenset({"admin"}))

    mutated = 0

    async def _on_mutated() -> None:
        nonlocal mutated
        mutated += 1

    pagination: dict[str, Any] = {
        "rowsPerPage": 15,
        "sortBy": "job_id",
        "descending": False,
    }
    await jobs_mod.render_jobs_section(
        pipeline,
        ident,
        jobs=[p_job],
        on_mutated=_on_mutated,
        pagination_state=pagination,
    )
    events["update:pagination"](
        SimpleNamespace(args={"sortBy": "status", "descending": True, "page": 2})
    )
    assert pagination["sortBy"] == "status"
    assert pagination["descending"] is True
    await events["inspect_job"](SimpleNamespace(args={"job_id": "j-pend"}))
    await events["rowClick"](SimpleNamespace(args=[None, {"job_id": "j-pend"}, 0]))
    await events["hold_job"](SimpleNamespace(args={"job_id": "j-pend"}))
    await events["release_job"](SimpleNamespace(args={"job_id": "j-pend"}))
    await events["cancel_job"](SimpleNamespace(args={"job_id": "j-pend"}))
    events["cancel_run"](SimpleNamespace(args={"run_id": "r-1"}))
    await dialog_btns["Confirm Cancel Run"]()
    assert mutated == 4
