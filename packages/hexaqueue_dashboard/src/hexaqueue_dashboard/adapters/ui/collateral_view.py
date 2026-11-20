"""Collateral & Quarantine management board for the Hexaqueue Operator Console.

Notes/Architectural Intent:
    Renders staged and approved CAS collateral bundles in a compact, sortable,
    paginated `ui.table` matching the Jobs and Active Nodes boards, complete
    with stacked WCAG AA Kind/Tier and Scan Status badges, newline-separated
    admin worker cache lists, a right-hand slide-over inspection drawer, and
    RBAC-gated Promote / Delete actions.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import nullcontext
from datetime import timedelta
from typing import Any

from hexastack_auth.domain.models import Identity
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_ui.adapters.nicegui import dispatch_command, dispatch_query
from nicegui import ui

from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralState,
    CollateralTier,
)
from hexaqueue_core.domain.cqrs import (
    DeleteCollateralCommand,
    ListCollateralQuery,
    ListComputeNodesQuery,
    PromoteCollateralCommand,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState
from hexaqueue_core.domain.telemetry import NodeTelemetryPulse
from hexaqueue_dashboard.adapters.ui.state import DrawerUIState

_SCAN_BADGE_COLORS: dict[CollateralState, str] = {
    CollateralState.REGISTERED: "grey",
    CollateralState.UPLOADED: "info",
    CollateralState.SCANNING: "warning",
    CollateralState.APPROVED: "positive",
    CollateralState.QUARANTINED: "negative",
    CollateralState.REJECTED: "negative",
}

_SCAN_BADGE_BG: dict[CollateralState, str] = {
    CollateralState.REGISTERED: "#374151",
    CollateralState.UPLOADED: "#1d4ed8",
    CollateralState.SCANNING: "#a16207",
    CollateralState.APPROVED: "#15803d",
    CollateralState.QUARANTINED: "#b91c1c",
    CollateralState.REJECTED: "#991b1b",
}

_TIER_BADGE_BG: dict[CollateralTier, str] = {
    CollateralTier.PERMANENT: "#1d4ed8",
    CollateralTier.TEMPORARY: "#4b5563",
}

COLLATERAL_TABLE_COLUMNS: list[dict[str, object]] = [
    {
        "name": "filename",
        "label": "Filename",
        "field": "filename",
        "sortable": True,
        "align": "left",
    },
    {
        "name": "kind_tier",
        "label": "Kind / Tier",
        "field": "kind_tier",
        "sortable": True,
        "align": "center",
    },
    {
        "name": "state",
        "label": "Scan Status",
        "field": "state",
        "sortable": True,
        "align": "center",
    },
    {
        "name": "owner",
        "label": "Owner",
        "field": "owner",
        "sortable": True,
        "align": "left",
    },
    {
        "name": "usage_display",
        "label": "Active Usage",
        "field": "usage_display",
        "sortable": True,
        "align": "left",
    },
    {
        "name": "auto_removal",
        "label": "Auto-Removal",
        "field": "auto_removal",
        "sortable": True,
        "align": "left",
    },
    {
        "name": "actions",
        "label": "Actions",
        "field": "actions",
        "sortable": False,
        "align": "right",
    },
]

_ADMIN_WORKER_CACHE_COLUMN: dict[str, object] = {
    "name": "worker_caches",
    "label": "Worker Caches",
    "field": "worker_caches",
    "sortable": True,
    "align": "left",
}


def compute_auto_removal_display(bundle: CollateralBundle) -> str:
    """Format scheduled auto-removal / TTL retention label for a bundle.

    Args:
        bundle: Target CollateralBundle domain model.

    Returns:
        Human-readable retention or scheduled eviction timestamp string.
    """
    if bundle.tier == CollateralTier.PERMANENT:
        return "Never (Permanent)"
    if bundle.ttl_seconds is not None:
        expires_at = bundle.last_accessed_at + timedelta(seconds=bundle.ttl_seconds)
        return expires_at.strftime("%Y-%m-%d %H:%M UTC")
    return "LRU / Default TTL"


def find_worker_cache_nodes(
    sha256_checksum: str,
    nodes: Sequence[Any],
) -> list[str]:
    """Identify worker nodes holding a cached copy of a CAS digest.

    Args:
        sha256_checksum: 64-char hex SHA-256 checksum of the collateral bundle.
        nodes: Active worker telemetry or ComputeNodeProfile snapshots.

    Returns:
        Sorted list of worker/node IDs whose ``cached_collateral_hashes``
        contains ``sha256_checksum``.
    """
    matched: list[str] = []
    for node in nodes:
        hashes = getattr(node, "cached_collateral_hashes", ()) or ()
        if sha256_checksum in hashes:
            ident = getattr(node, "worker_id", None) or getattr(node, "node_id", "")
            if ident:
                matched.append(str(ident))
    return sorted(matched)


def _active_jobs_for_bundle(bundle_id: str, jobs: list[JobSpec]) -> list[str]:
    """Return IDs of non-terminal jobs referencing ``bundle_id``."""
    return [
        job.id
        for job in jobs
        if job.status.state is not JobState.DONE and bundle_id in job.collateral_ids
    ]


def _can_delete_row(row: dict[str, Any], identity: Identity, is_admin: bool) -> bool:
    """Determine whether the caller is authorized to delete a collateral row."""
    if is_admin:
        return True
    return (
        row["owner"] == identity.user_id
        and row["tier"] == CollateralTier.TEMPORARY.value
    )


def build_collateral_rows(
    bundles: list[CollateralBundle],
    jobs: list[JobSpec],
    nodes: Sequence[Any],
    *,
    is_admin: bool,
    identity: Identity | None = None,
) -> list[dict[str, Any]]:
    """Transform collateral bundles into view-ready `ui.table` row dictionaries.

    Args:
        bundles: CollateralBundle instances authorized for the caller.
        jobs: Cluster JobSpec records for active-job reference checks.
        nodes: Active worker telemetry pulses for CAS cache cross-referencing.
        is_admin: Whether the caller has administrative visibility.
        identity: Optional caller Identity for per-row delete permission flags.

    Returns:
        List of row dictionaries containing metadata, scan/quarantine status,
        combined Kind/Tier sort key, active job usage, retention display,
        newline-separated worker cache lists, badge colors, and RBAC flags.
    """
    rows: list[dict[str, Any]] = []
    for bundle in bundles:
        active_job_ids = _active_jobs_for_bundle(bundle.id, jobs)
        in_use = bundle.active_pin_count > 0 or len(active_job_ids) > 0
        cached_nodes = (
            find_worker_cache_nodes(bundle.sha256_checksum, nodes) if is_admin else []
        )
        verdict = (
            bundle.quarantine_reason
            if is_admin and bundle.quarantine_reason
            else bundle.state.value
        )
        usage_display = (
            ", ".join(active_job_ids)
            if active_job_ids
            else f"{bundle.active_pin_count} pin(s)"
        )
        row: dict[str, Any] = {
            "id": bundle.id,
            "filename": bundle.filename,
            "kind": bundle.kind.value,
            "tier": bundle.tier.value,
            "kind_tier": f"{bundle.tier.value} / {bundle.kind.value}",
            "tier_bg": _TIER_BADGE_BG.get(bundle.tier, "#4b5563"),
            "owner": bundle.owner,
            "state": bundle.state.value,
            "badge_color": _SCAN_BADGE_COLORS.get(bundle.state, "grey"),
            "badge_bg": _SCAN_BADGE_BG.get(bundle.state, "#374151"),
            "verdict": verdict,
            "has_verdict_detail": bool(is_admin and verdict != bundle.state.value),
            "active_job_ids": active_job_ids,
            "active_pin_count": bundle.active_pin_count,
            "usage_display": usage_display,
            "in_use": in_use,
            "auto_removal": compute_auto_removal_display(bundle),
            "worker_caches": ", ".join(cached_nodes) if cached_nodes else "None",
            "worker_caches_multiline": (
                "\n".join(cached_nodes) if cached_nodes else "None"
            ),
            "cached_node_count": len(cached_nodes),
            "size_bytes": bundle.size_bytes,
            "sha256_checksum": bundle.sha256_checksum,
            "sha256_short": bundle.sha256_checksum[:12],
            "can_promote": bool(is_admin and bundle.tier == CollateralTier.TEMPORARY),
            "can_delete": (
                _can_delete_row(
                    {"owner": bundle.owner, "tier": bundle.tier.value},
                    identity,
                    is_admin,
                )
                if identity is not None
                else is_admin
            ),
        }
        rows.append(row)
    return rows


def _open_delete_dialog(
    pipeline: ExecutionPipeline,
    identity: Identity,
    row: dict[str, Any],
    *,
    is_admin: bool,
    on_mutated: Any,
) -> None:
    """Open a confirmation dialog before deleting a collateral bundle."""
    dialog = ui.dialog()
    with dialog, ui.card().classes("bg-slate-900 border border-slate-700 p-4 w-96"):
        ui.label("Confirm Collateral Deletion").classes("text-base font-semibold")
        ui.label(
            f"Delete '{row['filename']}' ({row['id']})? This cannot be undone."
        ).classes("text-sm text-slate-300 mt-1")
        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            ui.button("Cancel", on_click=dialog.close).props(
                'flat color="grey-3" aria-label="Cancel collateral deletion"'
            )

            async def _confirm_delete() -> None:
                dialog.close()
                try:
                    await dispatch_command(
                        pipeline,
                        DeleteCollateralCommand(
                            collateral_id=row["id"],
                            user_id=identity.user_id,
                            elevate=is_admin,
                        ),
                    )
                    ui.notify(f"Deleted collateral {row['filename']}", type="positive")
                    await on_mutated()
                except Exception as exc:  # noqa: BLE001
                    ui.notify(f"Delete failed: {exc}", type="negative")

            ui.button("Delete", color="negative", on_click=_confirm_delete).props(
                'aria-label="Confirm delete collateral"'
            )
    dialog.open()


def open_collateral_inspection_drawer(
    row: dict[str, Any],
    *,
    is_admin: bool,
    drawer_state: DrawerUIState | None = None,
) -> None:
    """Open slide-over inspection drawer for a collateral bundle.

    Args:
        row: Row dictionary produced by ``build_collateral_rows``.
        is_admin: Whether to include admin-only quarantine verdicts and cache nodes.
        drawer_state: Optional ``DrawerUIState`` hosting the persistent drawer.

    Notes/Architectural Intent:
        Uses the same right-anchored full-height slide-over drawer pattern as
        ``open_job_inspection_drawer`` and ``open_node_inspection_drawer`` to keep
        the main Collateral table narrow while preserving full CAS diagnostics.
    """
    host_ctx = (
        drawer_state.host
        if drawer_state is not None and drawer_state.host is not None
        else nullcontext()
    )
    with (
        host_ctx,
        ui.dialog().props("position=right full-height") as drawer,
        ui.card().classes("w-[480px] max-w-full h-full overflow-y-auto p-6"),
    ):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label(f"Collateral: {row['filename']}").classes("text-lg font-semibold")
            ui.button(icon="close", on_click=drawer.close).props(
                'flat round dense aria-label="Close collateral inspection drawer"'
            )

        with ui.row().classes("items-center gap-2 mt-2"):
            ui.badge(row["state"]).style(
                f"background-color: {row['badge_bg']}; color: #ffffff; font-weight: 700;"
            )
            ui.badge(row["tier"]).style(
                f"background-color: {row['tier_bg']}; color: #ffffff; font-weight: 700;"
            )
            ui.badge(row["kind"]).style(
                "background-color: #334155; color: #ffffff; font-weight: 700;"
            )

        details = [
            f"Bundle ID: {row['id']}",
            f"Owner: {row['owner']}",
            f"SHA-256: {row.get('sha256_checksum', row['sha256_short'])}",
            f"Size: {row['size_bytes']} bytes",
            f"Active Usage: {row['usage_display']}",
            f"Auto-Removal: {row['auto_removal']}",
        ]
        for line in details:
            ui.label(line).classes("text-xs font-mono text-slate-200 mt-1 break-all")

        if is_admin:
            ui.label("Worker CAS Cache Copies").classes(
                "text-sm font-semibold text-slate-100 mt-4"
            )
            ui.label(row["worker_caches_multiline"]).classes(
                "text-xs font-mono text-slate-300 whitespace-pre-line mt-1"
            )
            if row.get("has_verdict_detail"):
                ui.label("Quarantine Verdict").classes(
                    "text-sm font-semibold text-amber-300 mt-4"
                )
                ui.label(row["verdict"]).classes("text-xs text-amber-200 mt-1")

        with ui.row().classes("w-full justify-end mt-6"):
            ui.button("Close", on_click=drawer.close).props(
                'flat color="grey-3" aria-label="Close collateral details"'
            )
    drawer.open()


def _wire_collateral_table_events(
    table: Any,
    rows_by_id: dict[str, dict[str, Any]],
    pipeline: ExecutionPipeline,
    identity: Identity,
    *,
    is_admin: bool,
    on_mutated: Any,
    drawer_state: DrawerUIState | None = None,
) -> None:
    """Attach inspect, promote, delete, and row-click handlers to the table."""

    def _resolve_row(args: Any) -> dict[str, Any] | None:
        if isinstance(args, list) and len(args) >= 2 and isinstance(args[1], dict):
            return rows_by_id.get(str(args[1].get("id", "")))
        if isinstance(args, dict):
            return rows_by_id.get(str(args.get("id", "")))
        return None

    def _on_inspect(ev: object) -> None:
        row = _resolve_row(getattr(ev, "args", None))
        if row is not None:
            open_collateral_inspection_drawer(
                row, is_admin=is_admin, drawer_state=drawer_state
            )

    async def _on_promote(ev: object) -> None:
        row = _resolve_row(getattr(ev, "args", None))
        if row is None or not row.get("can_promote"):
            return
        try:
            await dispatch_command(
                pipeline,
                PromoteCollateralCommand(
                    collateral_id=row["id"],
                    user_id=identity.user_id,
                    elevate=True,
                ),
            )
            ui.notify(f"Promoted {row['filename']} to PERMANENT", type="positive")
            await on_mutated()
        except Exception as exc:  # noqa: BLE001
            ui.notify(f"Promote failed: {exc}", type="negative")

    def _on_delete(ev: object) -> None:
        row = _resolve_row(getattr(ev, "args", None))
        if row is None or not row.get("can_delete") or row.get("in_use"):
            return
        _open_delete_dialog(
            pipeline,
            identity,
            row,
            is_admin=is_admin,
            on_mutated=on_mutated,
        )

    table.on("inspect_collateral", _on_inspect)
    table.on("rowClick", _on_inspect)
    table.on("promote_collateral", _on_promote)
    table.on("delete_collateral", _on_delete)


def _attach_collateral_slots(table: Any) -> None:
    """Register WCAG AA badge, multiline cache, and action slots on the table."""
    table.add_slot(
        "body-cell-kind_tier",
        """
        <q-td :props="props">
            <div class="column items-center q-gutter-xs">
                <q-badge
                    :style="{ backgroundColor: props.row.tier_bg, color: '#ffffff', fontWeight: 700 }"
                    class="px-2 py-0.5 text-xs rounded"
                >
                    {{ props.row.tier }}
                </q-badge>
                <q-badge
                    style="background-color: #334155; color: #ffffff; font-weight: 600;"
                    class="px-2 py-0.5 text-xs rounded"
                >
                    {{ props.row.kind }}
                </q-badge>
            </div>
        </q-td>
        """,
    )
    table.add_slot(
        "body-cell-state",
        """
        <q-td :props="props">
            <q-badge
                :style="{ backgroundColor: props.row.badge_bg, color: '#ffffff', fontWeight: 700 }"
                class="px-2 py-1 text-xs rounded"
            >
                {{ props.value }}
                <q-tooltip v-if="props.row.has_verdict_detail">
                    {{ props.row.verdict }}
                </q-tooltip>
            </q-badge>
        </q-td>
        """,
    )
    table.add_slot(
        "body-cell-worker_caches",
        """
        <q-td :props="props">
            <div class="whitespace-pre-line font-mono text-xs">
                {{ props.row.worker_caches_multiline }}
            </div>
        </q-td>
        """,
    )
    table.add_slot(
        "body-cell-actions",
        """
        <q-td :props="props">
            <div class="row justify-end q-gutter-xs no-wrap">
                <q-btn
                    dense flat round size="sm" icon="visibility" color="primary"
                    :aria-label="'Inspect collateral ' + props.row.filename"
                    @click.stop="$parent.$emit('inspect_collateral', props.row)"
                >
                    <q-tooltip>Inspect collateral metadata &amp; quarantine details</q-tooltip>
                </q-btn>
                <q-btn
                    v-if="props.row.can_promote"
                    dense flat round size="sm" icon="verified" color="blue-8"
                    :aria-label="'Promote ' + props.row.filename + ' to Permanent'"
                    @click.stop="$parent.$emit('promote_collateral', props.row)"
                >
                    <q-tooltip>Promote to Permanent</q-tooltip>
                </q-btn>
                <q-btn
                    v-if="props.row.can_delete"
                    :disable="props.row.in_use"
                    dense flat round size="sm" icon="delete" color="red-8"
                    :aria-label="'Delete collateral ' + props.row.filename"
                    @click.stop="$parent.$emit('delete_collateral', props.row)"
                >
                    <q-tooltip>
                        {{ props.row.in_use ? 'Cannot delete collateral referenced by active jobs or pinned' : 'Delete collateral' }}
                    </q-tooltip>
                </q-btn>
            </div>
        </q-td>
        """,
    )


async def render_collateral_section(
    pipeline: ExecutionPipeline,
    identity: Identity,
    jobs: list[JobSpec],
    nodes: list[NodeTelemetryPulse],
    *,
    is_admin: bool,
    on_mutated: Any,
    drawer_state: DrawerUIState | None = None,
) -> None:
    """Render the Collateral & Quarantine management table board.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
        jobs: Current cluster JobSpec list for active-job reference checks.
        nodes: Current worker NodeTelemetryPulse list for CAS cache visibility.
        is_admin: Whether the caller is viewing with administrative privileges.
        on_mutated: Async callback invoked after promote or delete mutations.
        drawer_state: Optional ``DrawerUIState`` for persistent slide-over drawer.

    Notes/Architectural Intent:
        Uses the same sortable, paginated `ui.table` layout, WCAG AA badge
        palette, right-hand slide-over inspection drawer, and compact icon
        action slot as the Jobs and Active Nodes boards.
    """
    ui.label("Collateral & Quarantine").classes("text-lg font-semibold mt-4")

    try:
        bundles = await dispatch_query(
            pipeline,
            ListCollateralQuery(user_id=identity.user_id, elevate=is_admin),
        )
    except Exception as exc:  # noqa: BLE001
        ui.label(f"Collateral inventory unavailable: {exc}").classes(
            "text-sm text-amber-300 mt-2"
        )
        return

    cache_nodes: Sequence[Any] = nodes
    if is_admin:
        try:
            compute_nodes = await dispatch_query(
                pipeline,
                ListComputeNodesQuery(user_id=identity.user_id, elevate=True),
            )
            if compute_nodes:
                cache_nodes = [*nodes, *compute_nodes]
        except Exception:  # noqa: BLE001
            cache_nodes = nodes

    rows = build_collateral_rows(
        bundles, jobs, cache_nodes, is_admin=is_admin, identity=identity
    )
    if not rows:
        ui.label("No collateral bundles registered.").classes(
            "text-sm text-slate-300 mt-2"
        )
        return

    columns = (
        [
            *COLLATERAL_TABLE_COLUMNS[:-1],
            _ADMIN_WORKER_CACHE_COLUMN,
            COLLATERAL_TABLE_COLUMNS[-1],
        ]
        if is_admin
        else list(COLLATERAL_TABLE_COLUMNS)
    )
    table = ui.table(
        columns=columns,
        rows=rows,
        row_key="id",
        pagination={"rowsPerPage": 15, "sortBy": "filename", "descending": False},
    ).classes("w-full mt-2")

    _attach_collateral_slots(table)
    rows_by_id = {row["id"]: row for row in rows}
    _wire_collateral_table_events(
        table,
        rows_by_id,
        pipeline,
        identity,
        is_admin=is_admin,
        on_mutated=on_mutated,
        drawer_state=drawer_state,
    )


__all__ = [
    "build_collateral_rows",
    "COLLATERAL_TABLE_COLUMNS",
    "compute_auto_removal_display",
    "find_worker_cache_nodes",
    "open_collateral_inspection_drawer",
    "render_collateral_section",
]
