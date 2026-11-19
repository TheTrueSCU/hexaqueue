"""Unit tests for the Collateral & Quarantine dashboard view."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from hexastack_auth.domain.models import Identity

from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralState,
    CollateralTier,
)
from hexaqueue_core.domain.cqrs import (
    DeleteCollateralCommand,
    ListCollateralQuery,
    PromoteCollateralCommand,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState, JobStatus
from hexaqueue_core.domain.node import ComputeNodeProfile
from hexaqueue_dashboard.adapters.ui import collateral_view as col_mod


def _make_bundle(
    bundle_id: str,
    *,
    owner: str = "alice",
    tier: CollateralTier = CollateralTier.TEMPORARY,
    state: CollateralState = CollateralState.APPROVED,
    sha256: str = "a" * 64,
    ttl_seconds: int | None = None,
    quarantine_reason: str | None = None,
) -> CollateralBundle:
    active_uri = (
        f"/tmp/active/{bundle_id}" if state == CollateralState.APPROVED else None
    )
    return CollateralBundle(
        id=bundle_id,
        job_id="job-1",
        owner=owner,
        filename=f"{bundle_id}.tar.gz",
        size_bytes=4096,
        sha256_checksum=sha256,
        kind=CollateralKind.DATASET,
        tier=tier,
        state=state,
        staging_uri=f"/tmp/staging/{bundle_id}",
        active_uri=active_uri,
        quarantine_reason=quarantine_reason,
        ttl_seconds=ttl_seconds,
        last_accessed_at=datetime(2026, 11, 18, 12, 0, tzinfo=UTC),
    )


def test_collateral_row_helpers_and_rbac() -> None:
    """Verify auto-removal formatting, worker cache cross-ref, and RBAC row shaping."""
    t0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
    b_perm = _make_bundle("col-perm", tier=CollateralTier.PERMANENT)
    b_ttl = _make_bundle("col-ttl", ttl_seconds=3600, sha256="b" * 64)
    b_quar = _make_bundle(
        "col-quar",
        state=CollateralState.QUARANTINED,
        quarantine_reason="YARA match: SuspiciousMacro",
        sha256="c" * 64,
    )

    perm_disp = col_mod.compute_auto_removal_display(b_perm)
    assert perm_disp == "Never (Permanent)"

    ttl_disp = col_mod.compute_auto_removal_display(b_ttl)
    expected_ttl = (t0 + timedelta(seconds=3600)).strftime("%Y-%m-%d %H:%M UTC")
    assert ttl_disp == expected_ttl

    lru_disp = col_mod.compute_auto_removal_display(b_quar)
    assert lru_disp == "LRU / Default TTL"

    nodes = [
        ComputeNodeProfile(
            node_id="worker-1",
            cached_collateral_hashes=frozenset({"b" * 64}),
        ),
        ComputeNodeProfile(
            node_id="worker-2",
            cached_collateral_hashes=frozenset({"b" * 64}),
        ),
    ]
    matched_nodes = col_mod.find_worker_cache_nodes("b" * 64, nodes)
    assert matched_nodes == ["worker-1", "worker-2"]

    jobs = [
        JobSpec(
            id="job-active",
            run_id="run-1",
            name="train",
            command="echo ok",
            status=JobStatus(state=JobState.RUNNING),
            collateral_ids=["col-ttl"],
        )
    ]

    admin_rows = col_mod.build_collateral_rows(
        [b_ttl, b_quar], jobs, nodes, is_admin=True
    )
    assert admin_rows[0]["in_use"] is True
    assert admin_rows[0]["worker_caches"] == "worker-1, worker-2"
    assert admin_rows[1]["verdict"] == "YARA match: SuspiciousMacro"

    user_rows = col_mod.build_collateral_rows(
        [b_ttl, b_quar], jobs, nodes, is_admin=False
    )
    assert user_rows[0]["worker_caches"] == "None"
    assert user_rows[1]["verdict"] == "QUARANTINED"


@pytest.mark.asyncio
async def test_render_collateral_section_actions(
    monkeypatch: pytest.MonkeyPatch,
    fake_el: Any,
) -> None:
    """Verify Promote to Permanent and Delete actions dispatch CQRS commands."""
    buttons: dict[str, Any] = {}
    notifications: list[str] = []

    def _cap_button(label: str = "", *_a: object, **kwargs: Any) -> Any:
        el = fake_el()
        if "on_click" in kwargs:
            buttons[label] = kwargs["on_click"]
        return el

    fake_ui = SimpleNamespace(
        label=lambda *_a, **_k: fake_el(),
        card=lambda *_a, **_k: fake_el(),
        row=lambda *_a, **_k: fake_el(),
        badge=lambda *_a, **_k: fake_el(),
        dialog=lambda *_a, **_k: fake_el(),
        button=_cap_button,
        notify=lambda msg, **_k: notifications.append(msg),
    )
    monkeypatch.setattr(col_mod, "ui", fake_ui)

    b_temp = _make_bundle("col-unused", owner="alice", tier=CollateralTier.TEMPORARY)
    executed: list[Any] = []
    mutated_calls: list[bool] = []

    class _FakePipeline:
        def execute(self, msg: Any) -> Any:
            executed.append(msg)
            if isinstance(msg, ListCollateralQuery):
                return [b_temp]
            if isinstance(msg, PromoteCollateralCommand):
                return b_temp.model_copy(update={"tier": CollateralTier.PERMANENT})
            if isinstance(msg, DeleteCollateralCommand):
                return b_temp.id
            return None

    async def _on_mutated() -> None:
        mutated_calls.append(True)

    ident = Identity(user_id="admin", roles=frozenset({"admin"}))
    pipeline: Any = _FakePipeline()
    await col_mod.render_collateral_section(
        pipeline,
        ident,
        [],
        [],
        is_admin=True,
        on_mutated=_on_mutated,
    )

    assert "Promote to Permanent" in buttons
    assert "Delete" in buttons

    await buttons["Promote to Permanent"]()
    promoted_cmds = [m for m in executed if isinstance(m, PromoteCollateralCommand)]
    assert len(promoted_cmds) == 1
    assert promoted_cmds[0].collateral_id == "col-unused"
    assert len(mutated_calls) == 1

    # Open delete confirmation dialog and confirm deletion
    buttons["Delete"]()
    await buttons["Delete"]()
    deleted_cmds = [m for m in executed if isinstance(m, DeleteCollateralCommand)]
    assert len(deleted_cmds) == 1
    assert deleted_cmds[0].collateral_id == "col-unused"
    assert len(mutated_calls) == 2

    # Non-admin user cannot delete another owner's bundle
    alice_ident = Identity(user_id="bob", roles=frozenset({"user"}))
    buttons.clear()
    await col_mod.render_collateral_section(
        pipeline,
        alice_ident,
        [],
        [],
        is_admin=False,
        on_mutated=_on_mutated,
    )
    assert "Promote to Permanent" not in buttons
    assert "Delete" not in buttons
