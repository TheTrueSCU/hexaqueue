"""Unit tests for Fair-Share hierarchy and OCI worker pool quota view."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from hexastack_auth.domain.models import Identity

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.cqrs import ClusterStatsReport
from hexaqueue_core.domain.explainability import (
    FairShareNodeReport,
    FairShareTreeReport,
)
from hexaqueue_dashboard.adapters.ui import fairshare_view as fs_mod
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


@pytest.mark.asyncio
async def test_fairshare_view_rendering(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: type,
) -> None:
    """Verify Fair-Share tree building, quota cards, and error fallback."""
    root = FairShareNodeReport(
        id="root",
        shares=100.0,
        target_share=1.0,
        raw_usage=10.0,
        decayed_usage=5.0,
        fairshare_factor=1.0,
        children=[
            FairShareNodeReport(
                id="alice",
                parent_id="root",
                shares=50.0,
                target_share=0.5,
                raw_usage=10.0,
                decayed_usage=5.0,
                fairshare_factor=0.75,
            )
        ],
    )
    tree_nodes = fs_mod.build_fairshare_tree_nodes(root)
    assert len(tree_nodes) == 1
    assert tree_nodes[0]["id"] == "fs:root"

    labels: list[str] = []
    fake_ui = SimpleNamespace(
        label=lambda text="", *_a, **_k: labels.append(str(text)) or fake_el(),
        row=lambda *_a, **_k: fake_el(),
        card=lambda *_a, **_k: fake_el(),
        tree=lambda *_a, **_k: fake_el(),
        table=lambda *_a, **_k: fake_el(),
    )
    monkeypatch.setattr(fs_mod, "ui", fake_ui)

    async def _fake_dispatch(_pipeline: object, _query: object) -> FairShareTreeReport:
        return FairShareTreeReport(
            root=root, half_life_seconds=3600.0, total_decayed_usage=5.0
        )

    monkeypatch.setattr(fs_mod, "dispatch_query", _fake_dispatch)

    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    pipeline = create_hexaqueue_execution_pipeline(controller=controller)
    ident = Identity(user_id="alice", roles=frozenset({"admin"}))
    pulse = NodeTelemetryPulse(
        worker_id="w-1",
        active_jobs=1,
        cpu_utilization_pct=15.0,
        memory_used_mb=1024,
        memory_total_mb=4096,
        scratch_used_mb=100,
        scratch_total_mb=1000,
        load_average=(0.5, 0.4, 0.3),
    )
    stats = ClusterStatsReport(active_workers=1, running_jobs=1, pending_jobs=0)

    await fs_mod.render_fairshare_section(pipeline, ident, [pulse], stats)
    has_pool = any("hq-worker-pool-a1" in lbl for lbl in labels)
    has_halflife = any("Half-Life: 3600s" in lbl for lbl in labels)
    assert has_pool is True
    assert has_halflife is True

    async def _fail_dispatch(_pipeline: object, _query: object) -> FairShareTreeReport:
        raise RuntimeError("boom")

    monkeypatch.setattr(fs_mod, "dispatch_query", _fail_dispatch)
    await fs_mod.render_fairshare_section(pipeline, ident, [], ClusterStatsReport())
    has_unavail = any("unavailable" in lbl for lbl in labels)
    assert has_unavail is True
