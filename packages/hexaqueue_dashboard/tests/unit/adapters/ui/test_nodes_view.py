"""Unit tests for Active Nodes table and diagrams cluster topology SVG."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from hexastack_auth.domain.models import Identity

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, JobStatus
from hexaqueue_dashboard.adapters.ui import nodes_view as nodes_mod
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


def test_build_node_rows_and_topology_svg(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: Any,
    tmp_path: Path,
) -> None:
    """Verify node table row formatting and diagrams SVG generation + fallback."""
    pulse = NodeTelemetryPulse(
        worker_id="oci-worker-1",
        active_jobs=1,
        cpu_utilization_pct=42.5,
        memory_used_mb=2048,
        memory_total_mb=8192,
        load_average=(1.25, 0.9, 0.7),
        scratch_used_mb=100,
        scratch_total_mb=1000,
    )
    running_job = JobSpec(
        id="j-1",
        run_id="r-1",
        name="task-1",
        command="echo ok",
        assigned_worker_id="oci-worker-1",
        status=JobStatus(state=JobState.RUNNING),
    )

    rows = nodes_mod.build_node_rows([pulse], [running_job])
    assert len(rows) == 1
    assert rows[0]["worker_id"] == "oci-worker-1"
    assert "j-1" in str(rows[0]["active_jobs"])
    assert rows[0]["cpu_pct"] == "42.5%"

    svg = nodes_mod.generate_cluster_topology_svg([pulse], [running_job])
    assert "<svg" in svg
    assert 'xlink:href="/' not in svg

    icon_file = tmp_path / "vm.png"
    icon_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    inlined_svg = nodes_mod._inline_svg_images(
        f'<svg><image xlink:href="{icon_file}"/></svg>'
    )
    assert "data:image/png;base64," in inlined_svg
    assert str(icon_file) not in inlined_svg

    # Exercise fallback SVG when Diagram raises
    nodes_mod._TOPOLOGY_SVG_CACHE.clear()
    monkeypatch.setattr(
        nodes_mod,
        "Diagram",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no dot")),
    )
    fallback_svg = nodes_mod.generate_cluster_topology_svg([pulse], [running_job])
    assert "<svg" in fallback_svg
    assert "Workers (1)" in fallback_svg

    rendered: list[str] = []
    fake_ui = SimpleNamespace(
        label=lambda *_a, **_k: fake_el(),
        table=lambda *_a, **_k: fake_el(),
        html=lambda content, **_k: rendered.append(str(content)),
    )
    monkeypatch.setattr(nodes_mod, "ui", fake_ui)
    nodes_mod.render_nodes_section([pulse], [running_job])
    nodes_mod.render_nodes_section([], [])
    assert len(rendered) == 2


@pytest.mark.asyncio
async def test_node_metrics_histogram_and_bastion_drawer(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: Any,
) -> None:
    """Verify per-node metrics histogram, drawer, and Bastion Session Launcher."""
    history: dict[str, list[dict[str, float | str]]] = {}
    t0 = datetime.now(UTC)
    p1 = NodeTelemetryPulse(
        worker_id="w-1",
        cpu_utilization_pct=42.5,
        memory_used_mb=2048,
        memory_total_mb=8192,
        scratch_used_mb=1024,
        scratch_total_mb=10240,
        load_average=(1.0, 0.9, 0.8),
        active_jobs=1,
        timestamp=t0,
    )
    p2 = p1.model_copy(
        update={
            "cpu_utilization_pct": 70.0,
            "timestamp": t0 + timedelta(seconds=5),
        }
    )
    empty_svg = nodes_mod.build_node_metrics_histogram_svg([], label="CPU %")
    assert "Awaiting telemetry samples" in empty_svg

    nodes_mod.record_node_metrics_samples(history, [p1])
    nodes_mod.record_node_metrics_samples(history, [p1])  # deduped same ts
    nodes_mod.record_node_metrics_samples(history, [p2])
    assert len(history["w-1"]) == 2
    hist_svg = nodes_mod.build_node_metrics_histogram_svg(history["w-1"], label="CPU %")
    assert "latest 70.0%" in hist_svg

    buttons: dict[str, Any] = {}
    html_out: list[str] = []

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
        html=lambda content, **_k: html_out.append(str(content)) or fake_el(),
        timer=lambda *_a, **_k: fake_el(),
    )
    monkeypatch.setattr(nodes_mod, "ui", fake_ui)

    controller = LocalSchedulerControllerAdapter(queue=InMemoryJobQueueAdapter())
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    ident = Identity(user_id="rjdw", roles=frozenset({"admin"}))

    await nodes_mod.open_node_inspection_drawer(
        p2,
        [],
        pipeline=pipeline,
        identity=ident,
        metrics_history=history,
    )
    await buttons["Launch Bastion Session"]()
    has_ssh_cmd = any("hq node ssh w-1" in chunk for chunk in html_out)
    assert has_ssh_cmd is True
    assert "Close Bastion Session" in buttons
    buttons["Close Bastion Session"]()
    assert "Launch Bastion Session" in buttons
