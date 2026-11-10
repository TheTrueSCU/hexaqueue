"""Hexaqueue OCI Pool Status Runner.

Executes pool inspection on the remote controller host via SSH or locally.
Usage:
    uv run scripts/ops/pool_status.py
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
        description="Query Hexaqueue OCI instance pool status via SSH to controller."
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("HEXAQUEUE_CLUSTER_HOST", DEFAULT_HOST),
        help=f"Controller public IP or hostname (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--user",
        default=os.environ.get("HEXAQUEUE_ADMIN_USER", DEFAULT_USER),
        help=f"SSH admin user (default: {DEFAULT_USER})",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run inspection locally instead of delegating to remote host via SSH",
    )
    args = parser.parse_args()

    if args.local:
        from scripts.ops.oci_inspect_pool import inspect_pool

        return inspect_pool()

    remote_cmd = (
        "cd /home/ubuntu/hexaqueue && "
        "/home/ubuntu/.local/bin/uv run scripts/ops/oci_inspect_pool.py"
    )
    ssh_cmd = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{args.user}@{args.host}",
        remote_cmd,
    ]

    print(f"Querying OCI instance pool via {args.user}@{args.host}...")
    try:
        proc = subprocess.run(ssh_cmd, check=False)
        return proc.returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
