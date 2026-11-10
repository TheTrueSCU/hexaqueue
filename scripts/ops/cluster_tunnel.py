"""Hexaqueue Zero-Trust Cluster Tunnel.

Opens a secure SSH port-forwarding tunnel to the Hexaqueue controller.
Usage:
    uv run scripts/ops/cluster_tunnel.py [--local-port 8000] [--host <ip>]
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_HOST = "129.146.115.79"
DEFAULT_USER = "hexaqueue-ci"
DEFAULT_PORT = 8000


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if local TCP port is already open and accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def is_cluster_healthy(port: int) -> bool:
    """Check if Hexaqueue cluster /health endpoint responds successfully."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/health", headers={"User-Agent": "hq-ops-tunnel"}
        )
        with urllib.request.urlopen(req, timeout=1.0) as resp:  # noqa: S310
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Establish SSH port-forward tunnel to Hexaqueue controller."
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("HEXAQUEUE_CLUSTER_HOST", DEFAULT_HOST),
        help=f"Controller public IP (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--user",
        default=os.environ.get("HEXAQUEUE_SSH_USER", DEFAULT_USER),
        help=f"SSH tunnel user (default: {DEFAULT_USER})",
    )
    parser.add_argument(
        "--local-port",
        type=int,
        default=int(os.environ.get("HEXAQUEUE_LOCAL_PORT", DEFAULT_PORT)),
        help=f"Local forwarding port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--remote-port",
        type=int,
        default=int(os.environ.get("HEXAQUEUE_REMOTE_PORT", DEFAULT_PORT)),
        help=f"Remote binding port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--identity",
        "-i",
        default=os.environ.get("HEXAQUEUE_SSH_KEY"),
        help="Path to SSH private key",
    )
    args = parser.parse_args()

    if is_port_in_use(args.local_port):
        if is_cluster_healthy(args.local_port):
            print(
                f"Cluster tunnel is already active and healthy at http://127.0.0.1:{args.local_port}"
            )
            return 0
        print(
            f"Warning: Port {args.local_port} is in use, but cluster health probe failed."
        )

    ssh_cmd = [
        "ssh",
        "-N",
        "-L",
        f"{args.local_port}:127.0.0.1:{args.remote_port}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=30",
    ]

    key_path = (
        Path(args.identity).expanduser()
        if args.identity
        else Path.home() / ".ssh" / "hexaqueue_ci"
    )
    default_id_key = Path.home() / ".ssh" / "id_ed25519"
    if key_path.exists():
        ssh_cmd.extend(["-i", str(key_path)])
    elif default_id_key.exists():
        ssh_cmd.extend(["-i", str(default_id_key)])

    ssh_cmd.append(f"{args.user}@{args.host}")

    print(
        f"Connecting zero-trust tunnel to {args.user}@{args.host} "
        f"(127.0.0.1:{args.local_port} -> remote:127.0.0.1:{args.remote_port})..."
    )
    print("Press Ctrl+C to terminate.")

    try:
        proc = subprocess.run(ssh_cmd, check=False)
        return proc.returncode
    except KeyboardInterrupt:
        print("\nTunnel terminated by user.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
