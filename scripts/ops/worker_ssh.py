"""Hexaqueue Worker Jump-Host SSH Runner.

Establishes an SSH session to private-subnet compute workers (10.0.2.x) via the controller.
Usage:
    uv run scripts/ops/worker_ssh.py <worker-ip> [command...]
    uv run scripts/ops/worker_ssh.py 10.0.2.202
    uv run scripts/ops/worker_ssh.py 10.0.2.202 'journalctl -u hexaqueue-worker.service -n 50'
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

DEFAULT_JUMP_HOST = "129.146.115.79"
DEFAULT_JUMP_USER = "ubuntu"
DEFAULT_WORKER_USER = "ubuntu"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SSH into private-subnet Hexaqueue worker via jump host."
    )
    parser.add_argument(
        "worker_ip",
        help="Private IP or hostname of target worker node (e.g. 10.0.2.202)",
    )
    parser.add_argument(
        "command",
        nargs="*",
        help="Optional command to execute on the remote worker node",
    )
    parser.add_argument(
        "--jump-host",
        default=os.environ.get("HEXAQUEUE_CLUSTER_HOST", DEFAULT_JUMP_HOST),
        help=f"Jump host public IP (default: {DEFAULT_JUMP_HOST})",
    )
    parser.add_argument(
        "--jump-user",
        default=os.environ.get("HEXAQUEUE_ADMIN_USER", DEFAULT_JUMP_USER),
        help=f"Jump host admin user (default: {DEFAULT_JUMP_USER})",
    )
    parser.add_argument(
        "--worker-user",
        default=DEFAULT_WORKER_USER,
        help=f"Worker SSH user (default: {DEFAULT_WORKER_USER})",
    )
    args = parser.parse_args()

    ssh_cmd = [
        "ssh",
        "-A",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-J",
        f"{args.jump_user}@{args.jump_host}",
    ]

    target = f"{args.worker_user}@{args.worker_ip}"
    ssh_cmd.append(target)

    if args.command:
        ssh_cmd.extend(args.command)
    else:
        ssh_cmd.insert(1, "-t")
        print(
            f"Opening interactive SSH shell into {target} via {args.jump_user}@{args.jump_host}..."
        )

    try:
        proc = subprocess.run(ssh_cmd, check=False)
        return proc.returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
