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

        def add_slot(self, *_a: object, **_k: object) -> None:
            return None

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


def test_history_analytics_and_svg_builders() -> None:
    """Verify compute_history_analytics and SVG chart builders across durations and outcomes."""
    from datetime import UTC, datetime, timedelta

    from hexaqueue_core.domain.job import JobSpec, JobStatus
    from hexaqueue_core.domain.lifecycle import JobState, TerminalOutcome
    from hexaqueue_dashboard.adapters.ui import history_view as hist_mod
    from hexaqueue_server.domain.models import RunStatusReport

    base = datetime(2026, 11, 18, 12, 0, 0, tzinfo=UTC)
    j1 = JobSpec(
        id="j-a",
        run_id="r-a",
        name="fast",
        command="true",
        created_at=base,
        updated_at=base + timedelta(seconds=5),
        status=JobStatus(state=JobState.DONE, outcome=TerminalOutcome.COMPLETED),
    )
    j2 = JobSpec(
        id="j-b",
        run_id="r-a",
        name="slow-fail",
        command="false",
        created_at=base,
        updated_at=base + timedelta(seconds=120),
        status=JobStatus(state=JobState.DONE, outcome=TerminalOutcome.FAILED),
    )
    j3 = JobSpec(
        id="j-c",
        run_id="r-a",
        name="cancelled",
        command="true",
        created_at=base,
        updated_at=base + timedelta(seconds=45),
        status=JobStatus(state=JobState.DONE, outcome=TerminalOutcome.CANCELLED),
    )

    job_stats = hist_mod.compute_history_analytics([j1, j2, j3], is_runs=False)
    assert job_stats["total"] == 3
    assert job_stats["failure_rate_pct"] == 33.3
    buckets = dict(job_stats["duration_buckets"])
    assert buckets["<10s"] == 1
    assert buckets["10-60s"] == 1
    assert buckets["1-5m"] == 1
    assert job_stats["outcome_counts"]["Completed"] == 1
    assert job_stats["outcome_counts"]["Failed"] == 1
    assert job_stats["outcome_counts"]["Cancelled"] == 1

    dur_svg = hist_mod.build_history_duration_histogram_svg(
        job_stats["duration_buckets"]
    )
    assert 'aria-label="Duration distribution histogram"' in dur_svg
    assert "<rect " in dur_svg

    out_svg = hist_mod.build_history_outcome_svg(job_stats["outcome_counts"])
    assert 'aria-label="Outcome and failure breakdown chart"' in out_svg
    assert "Completed" in out_svg

    run_rep = RunStatusReport(
        run_id="r-a",
        name="Run A",
        owner="rjdw",
        total_jobs=3,
        completed_jobs=1,
        failed_jobs=1,
        running_jobs=0,
        pending_jobs=0,
        state=JobState.DONE,
        outcome=TerminalOutcome.FAILED,
        created_at=base,
        updated_at=base + timedelta(seconds=120),
    )
    run_stats = hist_mod.compute_history_analytics([run_rep], is_runs=True)
    assert run_stats["total"] == 1
    assert run_stats["failure_rate_pct"] == 100.0
