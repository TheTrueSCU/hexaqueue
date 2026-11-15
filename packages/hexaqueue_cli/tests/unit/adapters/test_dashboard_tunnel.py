"""Unit tests for SSH ControlMaster dashboard tunnel adapter."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hexaqueue_cli.adapters import dashboard_tunnel


def test_tunnel_lifecycle_hermetic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify start, status check, and stop invoke ssh ControlMaster cleanly."""
    sock = tmp_path / "dashboard-tunnel.sock"
    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if "-M" in cmd:
            sock.write_text("")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(dashboard_tunnel.subprocess, "run", fake_run)

    inactive = dashboard_tunnel.is_tunnel_active(socket_path=sock)
    assert inactive is False

    started = dashboard_tunnel.start_tunnel(
        host="129.146.115.79",
        user="ubuntu",
        local_port=8080,
        remote_port=8080,
        socket_path=sock,
    )
    assert started is True

    active = dashboard_tunnel.is_tunnel_active(
        host="129.146.115.79",
        user="ubuntu",
        socket_path=sock,
    )
    assert active is True

    restarted = dashboard_tunnel.start_tunnel(
        host="129.146.115.79",
        user="ubuntu",
        socket_path=sock,
    )
    assert restarted is False

    stopped = dashboard_tunnel.stop_tunnel(
        host="129.146.115.79",
        user="ubuntu",
        socket_path=sock,
    )
    assert stopped is True
    assert not sock.exists()


def test_tunnel_validation_and_ssh_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify port range checks and SSH failure error surfacing."""
    sock = tmp_path / "bad.sock"
    with pytest.raises(ValueError, match="between 1 and 65535"):
        dashboard_tunnel.start_tunnel(local_port=70000, socket_path=sock)

    def failing_run(
        cmd: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            cmd, 255, stdout="", stderr="Permission denied"
        )

    monkeypatch.setattr(dashboard_tunnel.subprocess, "run", failing_run)
    with pytest.raises(RuntimeError, match="Permission denied"):
        dashboard_tunnel.start_tunnel(host="129.146.115.79", socket_path=sock)
