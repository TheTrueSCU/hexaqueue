"""Probe Hexaqueue cluster capacity readiness and select discovery host for CI.

Notes/Architectural Intent:
    Invoked by the composite GitHub Action (``action.yml``) using only the Python
    standard library to either select the first reachable host from
    ``hq cluster discover --format json`` (``--select-host``) or verify
    ``GET /health/ready`` capacity readiness (``--check-ready``).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request


def select_first_ready_host(raw: str) -> str:
    """Return the first ``ONLINE`` or ``SSH_AVAILABLE`` host from discovery JSON.

    Args:
        raw: Raw stdout captured from ``hq cluster discover --format json``.

    Returns:
        Selected host string, or empty string if none are online.
    """
    clean = re.sub(r"\x1b\[[0-9;]*m", "", raw).strip()
    try:
        candidates = json.loads(clean, strict=False)
    except Exception:  # noqa: BLE001
        return ""
    if not isinstance(candidates, list):
        return ""
    for item in candidates:
        if isinstance(item, dict) and item.get("status") in (
            "ONLINE",
            "SSH_AVAILABLE",
        ):
            host = str(item.get("host", "")).strip()
            if host:
                return host
    return ""


def check_capacity_ready(url: str = "http://127.0.0.1:8000/health/ready") -> bool:
    """Check whether the controller's ``/health/ready`` endpoint reports ready capacity.

    Args:
        url: Readiness endpoint URL.

    Returns:
        True if the controller is ready (or on legacy 404 without ``/health/ready``),
        False if ``503 DEGRADED`` or unreachable.
    """
    if not url.startswith(("http://", "https://")):
        return False
    req = urllib.request.Request(  # noqa: S310
        url, headers={"User-Agent": "hexaqueue-ci-probe"}
    )
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
            state = str(data.get("capacity_state", "READY")).upper()
            if resp.status != 200 or state == "DEGRADED":
                return False
            active_workers = int(data.get("active_workers", 0) or 0)
            circuit = data.get("pool_circuit")
            circuit_state = (
                str(circuit.get("state", "CLOSED")).upper()
                if isinstance(circuit, dict)
                else "CLOSED"
            )
            return not (active_workers <= 1 and circuit_state == "OPEN")
    except urllib.error.HTTPError as err:
        return err.code == 404
    except Exception:  # noqa: BLE001
        return False


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for cluster discovery selection and readiness probing.

    Args:
        argv: Optional CLI argument vector.

    Returns:
        Exit code ``0`` on success, ``1`` when capacity is not ready.
    """
    parser = argparse.ArgumentParser(
        description="Select discovery host or probe Hexaqueue /health/ready capacity."
    )
    parser.add_argument(
        "--select-host",
        action="store_true",
        help="Read discovery JSON from stdin and print the first ready host.",
    )
    parser.add_argument(
        "--check-ready",
        action="store_true",
        help="Probe /health/ready and print 'true' or 'false'.",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000/health/ready",
        help="Target /health/ready endpoint URL.",
    )
    args = parser.parse_args(argv)

    if args.select_host:
        host = select_first_ready_host(sys.stdin.read())
        if host:
            sys.stdout.write(f"{host}\n")
        return 0

    if args.check_ready:
        ready = check_capacity_ready(args.url)
        sys.stdout.write("true\n" if ready else "false\n")
        return 0 if ready else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
