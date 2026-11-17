"""Unit tests for the History Explorer view and pagination helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from hexastack_auth.domain.models import Identity

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, JobStatus, TerminalOutcome
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_dashboard.adapters.ui import history_view as hist_mod
from hexaqueue_dashboard.adapters.ui import inspection_drawer as drawer_mod
from hexaqueue_dashboard.adapters.ui.state import DrawerUIState, HistoryUIState
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.domain.models import RunSubmission
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


@pytest.mark.asyncio
async def test_history_explorer_pagination_and_drawers(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: Any,
) -> None:
    """Verify history pagination, run/job filtering, and rowClick drawer opening."""
    items = list(range(55))
    page_items, total_pages, clamped = hist_mod.paginate_history_items(items, 2, 25)
    assert len(page_items) == 25
    assert total_pages == 3
    assert clamped == 2

    events: dict[str, Any] = {}
    buttons: dict[str, Any] = {}

    class _HistTable:
        def classes(self, *_a: object) -> _HistTable:
            return self

        def on(self, name: str, cb: Any) -> None:
            events[name] = cb

    def _cap_btn(label: str = "", *_a: object, **kwargs: Any) -> Any:
        if "on_click" in kwargs:
            buttons[label] = kwargs["on_click"]
        return fake_el()

    fake_ui = SimpleNamespace(
        label=lambda *_a, **_k: fake_el(),
        row=lambda *_a, **_k: fake_el(),
        column=lambda *_a, **_k: fake_el(),
        card=lambda *_a, **_k: fake_el(),
        dialog=lambda *_a, **_k: fake_el(),
        button=_cap_btn,
        input=lambda *_a, **_k: fake_el(),
        select=lambda *_a, **_k: fake_el(),
        table=lambda *_a, **_k: _HistTable(),
        html=lambda *_a, **_k: fake_el(),
        notify=lambda *_a, **_k: None,
        navigate=SimpleNamespace(reload=lambda: None),
    )
    monkeypatch.setattr(hist_mod, "ui", fake_ui)
    monkeypatch.setattr(drawer_mod, "ui", fake_ui)

    job = JobSpec(
        id="j-hist-1",
        run_id="r-hist-1",
        name="hist-job",
        command="echo ok",
        status=JobStatus(state=JobState.DONE, outcome=TerminalOutcome.COMPLETED),
    )
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    run_report = await controller.submit_run(
        RunSubmission(run_spec=RunSpec(id="r-hist-1", name="hist-run"), jobs=[job])
    )
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    ident = Identity(user_id="rjdw", roles=frozenset({"admin"}))

    refreshed = 0

    def _on_refresh() -> None:
        nonlocal refreshed
        refreshed += 1

    state = HistoryUIState()
    drawer_state = DrawerUIState(host=fake_el())
    hist_mod.render_history_section(
        pipeline,
        ident,
        [run_report],
        [job],
        state,
        drawer_state,
        on_refresh=_on_refresh,
    )
    await events["rowClick"](SimpleNamespace(args=[None, {"job_id": "j-hist-1"}, 0]))
    buttons["Runs History"]()
    assert state.kind == "runs"
    assert refreshed == 1

    hist_mod.render_history_section(
        pipeline,
        ident,
        [run_report],
        [job],
        state,
        drawer_state,
        on_refresh=_on_refresh,
    )
    await events["rowClick"](SimpleNamespace(args=[None, {"run_id": "r-hist-1"}, 0]))
