"""SSH ControlMaster tunnel adapter for Hexaqueue standalone dashboard access.

Notes/Architectural Intent:
    Manages a persistent, idempotent SSH local port-forward using a Unix
    ControlMaster socket so CLI subcommands can start, inspect, open, and
    cleanly tear down the dashboard tunnel without tracking raw PIDs.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

DEFAULT_SOCKET_PATH = Path.home() / ".hexaqueue" / "dashboard-tunnel.sock"


def _validate_port(port: int, label: str) -> int:
    if not 1 <= port <= 65535:
        raise ValueError(f"{label} port must be between 1 and 65535, got {port}")
    return port


def _resolve_target(host: str | None, user: str | None) -> str:
    resolved_host = (
        host or os.environ.get("HEXAQUEUE_CLUSTER_HOST") or "129.146.115.79"
    ).strip()
    resolved_user = (user or os.environ.get("HEXAQUEUE_SSH_USER") or "ubuntu").strip()
    if not resolved_host or not resolved_user:
        raise ValueError("Both SSH host and user must be non-empty.")
    return f"{resolved_user}@{resolved_host}"


def is_tunnel_active(
    *,
    host: str | None = None,
    user: str | None = None,
    socket_path: Path = DEFAULT_SOCKET_PATH,
) -> bool:
    """Check whether the SSH ControlMaster dashboard tunnel is currently active.

    Args:
        host: Remote controller host (defaults to HEXAQUEUE_CLUSTER_HOST).
        user: Remote SSH user (defaults to HEXAQUEUE_SSH_USER or 'ubuntu').
        socket_path: ControlMaster Unix socket path.

    Returns:
        True if the ControlMaster socket responds cleanly, otherwise False.
    """
    if not socket_path.exists():
        return False
    target = _resolve_target(host, user)
    res = subprocess.run(
        ["ssh", "-S", str(socket_path), "-O", "check", target],
        capture_output=True,
        text=True,
        check=False,
    )
    return res.returncode == 0


def start_tunnel(
    *,
    host: str | None = None,
    user: str | None = None,
    local_port: int = 8080,
    remote_port: int = 8080,
    socket_path: Path = DEFAULT_SOCKET_PATH,
) -> bool:
    """Start an SSH local port-forward tunnel if not already active.

    Args:
        host: Remote controller host.
        user: Remote SSH user.
        local_port: Local loopback port to bind.
        remote_port: Remote loopback dashboard port on the OCI host.
        socket_path: ControlMaster Unix socket path.

    Returns:
        True if a new tunnel was started, False if one was already active.

    Raises:
        RuntimeError: If SSH fails to establish the tunnel.
        ValueError: If ports or target host/user are invalid.
    """
    lport = _validate_port(local_port, "local")
    rport = _validate_port(remote_port, "remote")
    if is_tunnel_active(host=host, user=user, socket_path=socket_path):
        return False

    if socket_path.exists():
        socket_path.unlink(missing_ok=True)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.parent.chmod(0o700)

    target = _resolve_target(host, user)
    res = subprocess.run(
        [
            "ssh",
            "-M",
            "-S",
            str(socket_path),
            "-fN",
            "-L",
            f"127.0.0.1:{lport}:127.0.0.1:{rport}",
            "-o",
            "ExitOnForwardFailure=yes",
            target,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        detail = res.stderr.strip() or res.stdout.strip() or f"exit {res.returncode}"
        raise RuntimeError(
            f"Failed to start dashboard SSH tunnel to {target}: {detail}"
        )
    return True


def stop_tunnel(
    *,
    host: str | None = None,
    user: str | None = None,
    socket_path: Path = DEFAULT_SOCKET_PATH,
) -> bool:
    """Tear down the active SSH ControlMaster dashboard tunnel if running.

    Args:
        host: Remote controller host.
        user: Remote SSH user.
        socket_path: ControlMaster Unix socket path.

    Returns:
        True if an active tunnel was stopped, False if none was running.
    """
    if not is_tunnel_active(host=host, user=user, socket_path=socket_path):
        socket_path.unlink(missing_ok=True)
        return False

    target = _resolve_target(host, user)
    subprocess.run(
        ["ssh", "-S", str(socket_path), "-O", "exit", target],
        capture_output=True,
        text=True,
        check=False,
    )
    socket_path.unlink(missing_ok=True)
    return True


__all__ = [
    "DEFAULT_SOCKET_PATH",
    "is_tunnel_active",
    "start_tunnel",
    "stop_tunnel",
]
