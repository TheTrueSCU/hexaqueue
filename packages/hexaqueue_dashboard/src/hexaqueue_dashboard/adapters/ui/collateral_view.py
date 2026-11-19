"""Collateral & Quarantine management view for the Hexaqueue Operator Console.

Notes/Architectural Intent:
    Surfaces staged and approved CAS collateral bundles, quarantine scan
    verdicts, active job references, scheduled auto-removal / TTL timestamps,
    worker node CAS cache copies, and RBAC-scoped retention actions
    (Promote to Permanent, guarded Delete).
"""

from __future__ import annotations

from collections.abc import Sequence
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

_SCAN_BADGE_COLORS: dict[CollateralState, str] = {
    CollateralState.REGISTERED: "grey",
    CollateralState.UPLOADED: "info",
    CollateralState.SCANNING: "warning",
    CollateralState.APPROVED: "positive",
    CollateralState.QUARANTINED: "negative",
    CollateralState.REJECTED: "negative",
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


def build_collateral_rows(
    bundles: list[CollateralBundle],
    jobs: list[JobSpec],
    nodes: Sequence[Any],
    *,
    is_admin: bool,
) -> list[dict[str, Any]]:
    """Transform collateral bundles into view-ready row dictionaries.

    Args:
        bundles: CollateralBundle instances authorized for the caller.
        jobs: Cluster JobSpec records for active-job reference checks.
        nodes: Active worker telemetry pulses for CAS cache cross-referencing.
        is_admin: Whether the caller has administrative visibility.

    Returns:
        List of row dictionaries containing metadata, scan/quarantine status,
        active job usage, retention display, and admin-scoped worker cache copies.
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
        rows.append(
            {
                "id": bundle.id,
                "filename": bundle.filename,
                "kind": bundle.kind.value,
                "tier": bundle.tier.value,
                "owner": bundle.owner,
                "state": bundle.state.value,
                "badge_color": _SCAN_BADGE_COLORS.get(bundle.state, "grey"),
                "verdict": verdict,
                "active_job_ids": active_job_ids,
                "active_pin_count": bundle.active_pin_count,
                "in_use": in_use,
                "auto_removal": compute_auto_removal_display(bundle),
                "worker_caches": ", ".join(cached_nodes) if cached_nodes else "None",
                "cached_node_count": len(cached_nodes),
                "size_bytes": bundle.size_bytes,
                "sha256_short": bundle.sha256_checksum[:12],
            }
        )
    return rows


def _can_delete_row(row: dict[str, Any], identity: Identity, is_admin: bool) -> bool:
    """Determine whether the caller is authorized to delete a collateral row."""
    if is_admin:
        return True
    return (
        row["owner"] == identity.user_id
        and row["tier"] == CollateralTier.TEMPORARY.value
    )


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


def _render_row_actions(
    pipeline: ExecutionPipeline,
    identity: Identity,
    row: dict[str, Any],
    *,
    is_admin: bool,
    on_mutated: Any,
) -> None:
    """Render Promote to Permanent and guarded Delete buttons for one row."""
    with ui.row().classes("items-center gap-2"):
        if is_admin and row["tier"] == CollateralTier.TEMPORARY.value:

            async def _promote() -> None:
                try:
                    await dispatch_command(
                        pipeline,
                        PromoteCollateralCommand(
                            collateral_id=row["id"],
                            user_id=identity.user_id,
                            elevate=True,
                        ),
                    )
                    ui.notify(
                        f"Promoted {row['filename']} to PERMANENT", type="positive"
                    )
                    await on_mutated()
                except Exception as exc:  # noqa: BLE001
                    ui.notify(f"Promote failed: {exc}", type="negative")

            ui.button(
                "Promote to Permanent",
                icon="verified",
                on_click=_promote,
            ).props(
                f'size="sm" color="primary" aria-label="Promote {row["filename"]} to Permanent"'
            )

        if _can_delete_row(row, identity, is_admin):
            delete_btn = ui.button(
                "Delete",
                icon="delete",
                color="negative",
                on_click=lambda r=row: _open_delete_dialog(
                    pipeline,
                    identity,
                    r,
                    is_admin=is_admin,
                    on_mutated=on_mutated,
                ),
            ).props(f'size="sm" flat aria-label="Delete collateral {row["filename"]}"')
            if row["in_use"]:
                delete_btn.props("disable")
                delete_btn.tooltip(
                    "Cannot delete collateral referenced by active jobs or pinned"
                )


def _render_collateral_card(
    pipeline: ExecutionPipeline,
    identity: Identity,
    row: dict[str, Any],
    *,
    is_admin: bool,
    on_mutated: Any,
) -> None:
    """Render a single collateral bundle card with metadata and row actions."""
    with ui.card().classes("w-full bg-slate-900 border border-slate-800 p-3 mt-2"):
        with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"):
            with ui.row().classes("items-center gap-2"):
                ui.label(row["filename"]).classes(
                    "text-sm font-semibold text-slate-100"
                )
                ui.badge(row["state"], color=row["badge_color"]).props(
                    f'aria-label="Scan status {row["state"]}"'
                )
                ui.badge(
                    row["tier"], color="info" if row["tier"] == "PERMANENT" else "grey"
                ).props(f'aria-label="Retention tier {row["tier"]}"')
                ui.label(row["kind"]).classes("text-xs font-mono text-slate-300")
            _render_row_actions(
                pipeline,
                identity,
                row,
                is_admin=is_admin,
                on_mutated=on_mutated,
            )

        usage_text = (
            f"Active jobs: {', '.join(row['active_job_ids'])}"
            if row["active_job_ids"]
            else f"Active pins: {row['active_pin_count']}"
        )
        details = [
            f"ID: {row['id']}",
            f"Owner: {row['owner']}",
            f"SHA-256: {row['sha256_short']}",
            f"Auto-removal: {row['auto_removal']}",
            usage_text,
        ]
        if is_admin:
            details.append(f"Worker cache copies: {row['worker_caches']}")
        ui.label(" | ".join(details)).classes("text-xs font-mono text-slate-300 mt-1")
        if is_admin and row["verdict"] != row["state"]:
            ui.label(f"Quarantine verdict: {row['verdict']}").classes(
                "text-xs text-amber-300 mt-1"
            )


async def render_collateral_section(
    pipeline: ExecutionPipeline,
    identity: Identity,
    jobs: list[JobSpec],
    nodes: list[NodeTelemetryPulse],
    *,
    is_admin: bool,
    on_mutated: Any,
) -> None:
    """Render the Collateral & Quarantine management tab.

    Args:
        pipeline: Shared CQRS ExecutionPipeline.
        identity: Verified caller Identity.
        jobs: Current cluster JobSpec list for active-job reference checks.
        nodes: Current worker NodeTelemetryPulse list for CAS cache visibility.
        is_admin: Whether the caller is viewing with administrative privileges.
        on_mutated: Async callback invoked after promote or delete mutations.

    Notes/Architectural Intent:
        Non-admin users see only bundles they own (with scan status, active job
        usage, auto-removal time, and delete on own unused TEMPORARY bundles).
        Administrators see all owners, quarantine verdicts, worker CAS cache
        copies, and full Promote to Permanent / Delete controls.
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

    rows = build_collateral_rows(bundles, jobs, cache_nodes, is_admin=is_admin)
    if not rows:
        ui.label("No collateral bundles registered.").classes(
            "text-sm text-slate-300 mt-2"
        )
        return

    for row in rows:
        _render_collateral_card(
            pipeline,
            identity,
            row,
            is_admin=is_admin,
            on_mutated=on_mutated,
        )


__all__ = [
    "build_collateral_rows",
    "compute_auto_removal_display",
    "find_worker_cache_nodes",
    "render_collateral_section",
]
