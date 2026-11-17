"""Unit tests for status badge palette, roll-ups, and live widget."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import (
    JobState,
    JobStatus,
    RunOutcome,
    RunState,
    TerminalOutcome,
)
from hexaqueue_dashboard.adapters.ui import status as status_mod
from hexaqueue_server.domain.models import RunStatusReport


def test_resolve_job_and_run_display_status() -> None:
    """Verify job and run display status roll-ups."""
    held_job = JobSpec(
        id="j-held",
        run_id="r-1",
        name="held",
        command="echo",
        status=JobStatus(state=JobState.BLOCKED, reason="Administratively held"),
    )
    done_job = JobSpec(
        id="j-done",
        run_id="r-1",
        name="done",
        command="echo",
        status=JobStatus(state=JobState.DONE, outcome=TerminalOutcome.COMPLETED),
    )
    held_res = status_mod.resolve_job_display_status(held_job)
    done_res = status_mod.resolve_job_display_status(done_job)
    assert held_res == "HELD"
    assert done_res == "COMPLETED"

    now = datetime.now(UTC)
    pending_run = RunStatusReport(
        run_id="r-pend",
        state=RunState.RUNNING,
        total_jobs=4,
        completed_jobs=0,
        failed_jobs=0,
        pending_jobs=4,
        running_jobs=0,
        created_at=now,
    )
    running_run = RunStatusReport(
        run_id="r-run",
        state=RunState.RUNNING,
        total_jobs=4,
        completed_jobs=1,
        failed_jobs=0,
        pending_jobs=2,
        running_jobs=1,
        created_at=now,
    )
    partial_run = RunStatusReport(
        run_id="r-part",
        state=RunState.RUNNING,
        total_jobs=4,
        completed_jobs=2,
        failed_jobs=0,
        pending_jobs=2,
        running_jobs=0,
        created_at=now,
    )
    done_run = RunStatusReport(
        run_id="r-done",
        state=RunState.DONE,
        outcome=RunOutcome.SUCCEEDED,
        total_jobs=4,
        completed_jobs=4,
        failed_jobs=0,
        pending_jobs=0,
        running_jobs=0,
        created_at=now,
    )
    pend_status = status_mod.resolve_run_display_status(pending_run)
    run_status = status_mod.resolve_run_display_status(running_run)
    part_status = status_mod.resolve_run_display_status(partial_run)
    done_status = status_mod.resolve_run_display_status(done_run)
    assert pend_status == "PENDING"
    assert run_status == "RUNNING"
    assert part_status == "IN_PROGRESS"
    assert done_status == "SUCCEEDED"

    assert status_mod.matches_status_filter("RUNNING", "ALL") is True
    assert status_mod.matches_status_filter("RUNNING", "ACTIVE") is True
    assert status_mod.matches_status_filter("COMPLETED", "ACTIVE") is False
    assert status_mod.matches_status_filter("FAILED", "TERMINAL") is True
    assert status_mod.matches_status_filter("PENDING", "TERMINAL") is False
    assert status_mod.matches_status_filter("FAILED", "FAILED") is True


def test_render_live_status_widget_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify full and tunnel-only live status widget rendering."""
    rendered_html: list[str] = []
    body_html: list[str] = []
    fake_ui = SimpleNamespace(
        html=lambda content, **_k: rendered_html.append(str(content)),
        add_body_html=lambda content: body_html.append(str(content)),
    )
    monkeypatch.setattr(status_mod, "ui", fake_ui)

    status_mod.render_live_status_widget("/static/live.js", mode="tunnel")
    assert 'data-mode="tunnel"' in rendered_html[0]
    assert "Tunnel Connected" in rendered_html[0]
    assert "/static/live.js" in body_html[0]

    status_mod.render_live_status_widget(None, mode="full")
    assert 'data-mode="full"' in rendered_html[1]
    assert "Connected" in rendered_html[1]
