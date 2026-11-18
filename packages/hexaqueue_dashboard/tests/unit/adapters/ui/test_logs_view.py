"""Unit tests for the shared live execution log viewer and dedicated logs page."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from hexastack_auth.domain.models import Identity

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, JobStatus
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_dashboard.adapters.ui import logs_view as logs_mod


def test_format_and_build_log_pre_html() -> None:
    """Verify log formatting, HTML escaping, and fallback states."""
    chunk = LogChunk(
        job_id="j-1",
        stream="stdout",
        content="<script>alert(1)</script> ok",
        offset=0,
        timestamp=datetime.now(UTC),
    )
    escaped = logs_mod.format_log_lines([chunk], None)
    assert escaped == "[stdout] &lt;script&gt;alert(1)&lt;/script&gt; ok"

    err_text = logs_mod.format_log_lines([], "boom")
    assert err_text == "Logs unavailable: boom"

    empty_text = logs_mod.format_log_lines([], None)
    assert empty_text == "No logs recorded yet."

    pre_html = logs_mod.build_log_pre_html([chunk], None, max_height="400px")
    assert 'aria-label="Job execution logs"' in pre_html
    assert "max-height:400px" in pre_html


@pytest.mark.asyncio
async def test_fetch_job_logs_and_live_viewer_polling(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: Any,
) -> None:
    """Verify GetLogsQuery polling, Live Tail switch toggle, and Open Page button."""
    navigated: list[tuple[str, bool]] = []
    buttons: dict[str, Any] = {}
    timers: list[Any] = []
    switches: list[Any] = []
    html_boxes: list[Any] = []

    def _cap_btn(label: str = "", *_a: object, **kwargs: Any) -> Any:
        if "on_click" in kwargs:
            buttons[label] = kwargs["on_click"]
        return fake_el()

    def _cap_switch(_label: str = "", **kwargs: Any) -> Any:
        el = fake_el()
        el.value = kwargs.get("value", False)
        el._handlers = []
        el.on_value_change = lambda fn: el._handlers.append(fn)
        switches.append(el)
        return el

    def _cap_timer(interval: float, callback: Any, *, active: bool = True) -> Any:
        timer = SimpleNamespace(interval=interval, callback=callback, active=active)
        timers.append(timer)
        return timer

    def _cap_html(content: str = "", **_k: Any) -> Any:
        box = fake_el()
        box.content = content
        box.update = lambda: None
        html_boxes.append(box)
        return box

    fake_ui = SimpleNamespace(
        row=lambda *_a, **_k: fake_el(),
        label=lambda *_a, **_k: fake_el(),
        switch=_cap_switch,
        button=_cap_btn,
        html=_cap_html,
        timer=_cap_timer,
        navigate=SimpleNamespace(
            to=lambda url, new_tab=False: navigated.append((url, new_tab))
        ),
    )
    monkeypatch.setattr(logs_mod, "ui", fake_ui)

    call_count = 0

    class _FakePipeline:
        async def execute(self, query: Any, **_k: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("transient error")
            return [
                LogChunk(
                    job_id=query.job_id,
                    stream="stdout",
                    content=f"line-{call_count}",
                    offset=call_count,
                    timestamp=datetime.now(UTC),
                )
            ]

    ident = Identity(user_id="rjdw", roles=frozenset({"admin"}))
    pipeline: Any = _FakePipeline()

    logs, err = await logs_mod.fetch_job_logs(pipeline, ident, "j-1")
    assert err is None
    assert len(logs) == 1
    assert logs[0].content == "line-1"

    logs_mod.render_live_log_viewer(
        logs,
        err,
        pipeline=pipeline,
        identity=ident,
        job_id="j-1",
        default_live_tail=False,
        full_page_url="/dashboard/ui/logs/j-1",
    )

    assert len(timers) == 1
    assert timers[0].active is False

    # Toggle Live Tail switch on -> timer becomes active.
    switches[0]._handlers[0](SimpleNamespace(value=True))
    assert timers[0].active is True

    # Open Page button navigates to dedicated log route in a new tab.
    buttons["Open Page"]()
    assert navigated == [("/dashboard/ui/logs/j-1", True)]

    # Refresh triggers GetLogsQuery error handling and updates log_box in place.
    await buttons["Refresh Logs"]()
    assert "Logs unavailable: transient error" in html_boxes[0].content


@pytest.mark.asyncio
async def test_render_live_logs_page(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: Any,
) -> None:
    """Verify dedicated live logs page renders landmarks, status badge, and active tail."""
    navigated: list[str] = []
    buttons: dict[str, Any] = {}
    timers: list[Any] = []
    badges: list[str] = []

    def _cap_btn(label: str = "", *_a: object, **kwargs: Any) -> Any:
        if "on_click" in kwargs:
            buttons[label] = kwargs["on_click"]
        return fake_el()

    def _cap_switch(_label: str = "", **kwargs: Any) -> Any:
        el = fake_el()
        el.value = kwargs.get("value", False)
        el.on_value_change = lambda _fn: None
        return el

    def _cap_timer(interval: float, callback: Any, *, active: bool = True) -> Any:
        timer = SimpleNamespace(interval=interval, callback=callback, active=active)
        timers.append(timer)
        return timer

    def _cap_badge(text: str = "", **_k: Any) -> Any:
        badges.append(text)
        return fake_el()

    fake_ui = SimpleNamespace(
        element=lambda *_a, **_k: fake_el(),
        row=lambda *_a, **_k: fake_el(),
        label=lambda *_a, **_k: fake_el(),
        switch=_cap_switch,
        button=_cap_btn,
        badge=_cap_badge,
        html=lambda *_a, **_k: fake_el(),
        timer=_cap_timer,
        navigate=SimpleNamespace(to=lambda url, **_k: navigated.append(url)),
    )
    monkeypatch.setattr(logs_mod, "ui", fake_ui)

    running_job = JobSpec(
        id="j-live",
        run_id="r-1",
        name="train",
        command="python train.py",
        status=JobStatus(state=JobState.RUNNING),
    )

    class _FakePipeline:
        async def execute(self, query: Any, **_k: Any) -> Any:
            if type(query).__name__ == "GetLogsQuery":
                return [
                    LogChunk(
                        job_id="j-live",
                        stream="stdout",
                        content="epoch 1",
                        offset=0,
                        timestamp=datetime.now(UTC),
                    )
                ]
            return [running_job]

    ident = Identity(user_id="rjdw", roles=frozenset({"admin"}))
    pipeline: Any = _FakePipeline()
    await logs_mod.render_live_logs_page(
        pipeline, ident, "j-live", back_url="/dashboard/ui"
    )

    assert badges == ["RUNNING"]
    assert timers[0].active is True
    await timers[0].callback()
    buttons["Open Console"]()
    assert navigated == ["/dashboard/ui"]


@pytest.mark.asyncio
async def test_render_live_log_viewer_hides_live_tail_for_terminal_job(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: Any,
) -> None:
    """Verify Live Tail switch and polling timer are omitted for terminal jobs."""
    switches: list[str] = []
    timers: list[Any] = []

    def _cap_switch(label: str = "", **_k: Any) -> Any:
        switches.append(label)
        return fake_el()

    def _cap_timer(interval: float, callback: Any, *, active: bool = True) -> Any:
        timer = SimpleNamespace(interval=interval, callback=callback, active=active)
        timers.append(timer)
        return timer

    fake_ui = SimpleNamespace(
        element=lambda *_a, **_k: fake_el(),
        row=lambda *_a, **_k: fake_el(),
        label=lambda *_a, **_k: fake_el(),
        switch=_cap_switch,
        button=lambda *_a, **_k: fake_el(),
        badge=lambda *_a, **_k: fake_el(),
        html=lambda *_a, **_k: fake_el(),
        timer=_cap_timer,
        navigate=SimpleNamespace(to=lambda *_a, **_k: None),
    )
    monkeypatch.setattr(logs_mod, "ui", fake_ui)

    ident = Identity(user_id="rjdw", roles=frozenset({"admin"}))
    pipeline: Any = SimpleNamespace()
    logs_mod.render_live_log_viewer(
        [],
        None,
        pipeline=pipeline,
        identity=ident,
        job_id="j-done",
        default_live_tail=True,
        is_terminal=True,
    )

    assert switches == []
    assert timers == []
