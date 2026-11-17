"""Unit tests for Active Nodes table and diagrams cluster topology SVG."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, JobStatus
from hexaqueue_dashboard.adapters.ui import nodes_view as nodes_mod
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


def test_build_node_rows_and_topology_svg(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: Any,
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
    assert "data:image/png;base64," in svg
    assert 'xlink:href="/' not in svg

    # Exercise fallback SVG when Diagram raises
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
