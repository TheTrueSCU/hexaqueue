"""Emit Hexaqueue fleet discovery & mesh summary to ``$GITHUB_STEP_SUMMARY``.

Notes/Architectural Intent:
    Invoked by the composite GitHub Action (``action.yml``) via
    ``${{ github.action_path }}/.github/scripts/emit_cluster_summary.py`` using
    only the Python standard library so it works before project dependencies
    are installed.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


def _parse_nodes(raw: str) -> list[dict[str, object]]:
    """Parse ANSI-stripped discovery JSON into a list of node dictionaries.

    Args:
        raw: Raw stdout captured from ``hq cluster discover --format json``.

    Returns:
        Parsed list of node metadata dictionaries, or an empty list on error.
    """
    clean = re.sub(r"\x1b\[[0-9;]*m", "", raw).strip()
    try:
        parsed = json.loads(clean, strict=False)
    except Exception:  # noqa: BLE001
        return []
    return parsed if isinstance(parsed, list) else []


def _format_markdown(
    nodes: list[dict[str, object]],
    *,
    cluster_ready: bool,
    selected_host: str,
    dashboard_url: str,
) -> str:
    """Render the fleet discovery and CLI status Markdown block.

    Args:
        nodes: Parsed node discovery dictionaries.
        cluster_ready: Whether an active zero-trust tunnel is established.
        selected_host: Selected controller host IP or hostname.
        dashboard_url: Optional explicit dashboard URL override.

    Returns:
        Formatted Markdown string ready to append to ``$GITHUB_STEP_SUMMARY``.
    """
    lines: list[str] = ["### 🌐 Hexaqueue Fleet Discovery & Mesh Summary", ""]
    if cluster_ready:
        lines.append(
            f"✅ **Status**: Active zero-trust tunnel connected to `{selected_host}`. "
            "Distributed cloud execution active."
        )
    else:
        lines.append(
            "⚠️ **Status**: No cloud controller reachable. Falling back to local in-process runner."
        )
    lines.append("")

    if nodes:
        lines.extend(
            [
                "| Host | Provider | User | Status | Latency | Source |",
                "|---|---|---|---|---|---|",
            ]
        )
        for node in nodes:
            host = node.get("host", "N/A")
            prov = node.get("provider", "N/A")
            user = node.get("user", "N/A")
            status = node.get("status", "UNKNOWN")
            raw_lat = node.get("latency_ms")
            lat = (
                f"{float(raw_lat):.1f}ms"
                if isinstance(raw_lat, (int, float))
                else "N/A"
            )
            src = node.get("source", "N/A")
            lines.append(
                f"| `{host}` | {prov} | `{user}` | **{status}** | {lat} | {src} |"
            )
        lines.append("")

    lines.extend(["#### Dashboard & CLI Status", ""])
    if dashboard_url:
        lines.append(f"- **Dashboard**: {dashboard_url}")
    else:
        lines.append(
            "- **Dashboard (via SSH tunnel)**: "
            "`http://127.0.0.1:8080/dashboard/ui` (`hq dashboard open`)"
        )
    if selected_host:
        lines.append(
            f"- **Cluster Tunnel**: `hq cluster tunnel --host {selected_host}`"
        )
    lines.append(
        "- **Cluster / Run / Job CLI**: "
        "`hq stat` · `hq nodes` · `hq top` · `hq status <run-or-job-id>` · `hq logs <job-id>`"
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    """Append the fleet discovery summary to ``$GITHUB_STEP_SUMMARY`` if set.

    Returns:
        Exit code ``0`` on completion.
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        sys.stderr.write("GITHUB_STEP_SUMMARY is not set; skipping fleet summary.\n")
        return 0

    nodes = _parse_nodes(os.environ.get("DISCOVERY_JSON", ""))
    markdown = _format_markdown(
        nodes,
        cluster_ready=os.environ.get("CLUSTER_READY", "") == "true",
        selected_host=os.environ.get("SELECTED_HOST", "").strip(),
        dashboard_url=os.environ.get("HEXAQUEUE_DASHBOARD_URL", "").strip(),
    )
    target = Path(summary_path)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(markdown)
    sys.stdout.write(
        f"Appended fleet summary to {summary_path} ({target.stat().st_size} bytes)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
