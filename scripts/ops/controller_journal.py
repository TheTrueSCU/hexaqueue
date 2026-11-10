"""Hexaqueue Controller Journal Logs.

Tails systemd journal logs from the active Hexaqueue controller daemon via SSH.
Usage:
    uv run scripts/ops/controller_journal.py [-f] [-n 100]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

DEFAULT_HOST = "129.146.115.79"
DEFAULT_USER = "ubuntu"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stream systemd journal logs for hexaqueue.service on controller."
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("HEXAQUEUE_CLUSTER_HOST", DEFAULT_HOST),
        help=f"Controller public IP (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--user",
        default=os.environ.get("HEXAQUEUE_ADMIN_USER", DEFAULT_USER),
        help=f"SSH admin user (default: {DEFAULT_USER})",
    )
    parser.add_argument(
        "-n",
        "--lines",
        type=int,
        default=50,
        help="Number of journal log lines to display (default: 50)",
    )
    parser.add_argument(
        "-f",
        "--follow",
        action="store_true",
        default=True,
        help="Follow log stream continuously (default: True)",
    )
    parser.add_argument(
        "--no-follow",
        dest="follow",
        action="store_false",
        help="Do not follow log stream",
    )
    args = parser.parse_args()

    follow_flag = "-f" if args.follow else ""
    remote_cmd = (
        f"sudo journalctl -u hexaqueue.service -n {args.lines} {follow_flag} --no-pager"
    )

    ssh_cmd = [
        "ssh",
        "-t",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{args.user}@{args.host}",
        remote_cmd,
    ]

    print(f"Connecting to {args.user}@{args.host} for hexaqueue.service journal...")
    try:
        proc = subprocess.run(ssh_cmd, check=False)
        return proc.returncode
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
