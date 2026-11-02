"""Unit tests for 'hq cluster' CLI commands and remote management helpers.

Notes/Architectural Intent:
    Verifies cluster management subcommands (status, ping, tunnel, sync) across healthy,
    unreachable, and error states using hermetic mocks without external network calls.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from hexaqueue_cli.commands.cluster import (
    _build_ssh_remote_sync_cmd,
    _build_ssh_tunnel_cmd,
    _find_ssh_tunnel_pids,
    _poll_health,
    _probe_health,
    _resolve_cluster_endpoint,
    _terminate_pids,
)
from hexaqueue_cli.main import app
from hexaqueue_core.domain.runner_config import HexaqueueProfileConfig

runner = CliRunner()


def test_probe_health_success() -> None:
    """Verify _probe_health succeeds when HTTP 200 JSON is returned.

    Notes/Architectural Intent:
        Validates decoding and latency measurement for healthy endpoints.
    """
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps({"status": "ok"}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        ok, payload, latency = _probe_health("http://127.0.0.1:8000")
        assert ok is True
        assert payload == {"status": "ok"}
        assert latency >= 0.0


def test_probe_health_failure() -> None:
    """Verify _probe_health returns (False, None, 0.0) upon network exception.

    Notes/Architectural Intent:
        Guarantees that connection refused, timeouts, or DNS failures degrade gracefully.
    """
    with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
        ok, payload, latency = _probe_health("http://127.0.0.1:8000")
        assert ok is False
        assert payload is None
        assert latency == 0.0


def test_poll_health_success_immediate() -> None:
    """Verify _poll_health returns immediately when healthy probe is detected.

    Notes/Architectural Intent:
        Verifies polling loop terminates upon first successful probe.
    """
    with patch(
        "hexaqueue_cli.commands.cluster._probe_health",
        return_value=(True, {"status": "ok"}, 12.5),
    ):
        ok, payload, latency = _poll_health(
            "http://127.0.0.1:8000", timeout_seconds=5.0
        )
        assert ok is True
        assert payload == {"status": "ok"}
        assert latency == 12.5


def test_poll_health_timeout() -> None:
    """Verify _poll_health returns failure when deadline expires.

    Notes/Architectural Intent:
        Prevents infinite hang if remote cluster fails to start.
    """
    with (
        patch(
            "hexaqueue_cli.commands.cluster._probe_health",
            return_value=(False, None, 0.0),
        ),
        patch("time.sleep", return_value=None),
    ):
        ok, payload, latency = _poll_health(
            "http://127.0.0.1:8000", timeout_seconds=0.01
        )
        assert ok is False
        assert payload is None
        assert latency == 0.0


def test_find_ssh_tunnel_pids() -> None:
    """Verify _find_ssh_tunnel_pids extracts numeric PIDs from pgrep output.

    Notes/Architectural Intent:
        Validates accurate parsing of process listing output.
    """
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "12345\n67890\ninvalid\n"

    with patch("subprocess.run", return_value=mock_proc):
        pids = _find_ssh_tunnel_pids(8000)
        assert pids == [12345, 67890]


def test_find_ssh_tunnel_pids_error() -> None:
    """Verify _find_ssh_tunnel_pids handles command exceptions cleanly.

    Notes/Architectural Intent:
        Ensures missing pgrep or permissions do not crash tunnel checks.
    """
    with patch("subprocess.run", side_effect=OSError("pgrep not found")):
        pids = _find_ssh_tunnel_pids(8000)
        assert pids == []


def test_terminate_pids() -> None:
    """Verify _terminate_pids sends SIGTERM and counts terminated processes.

    Notes/Architectural Intent:
        Ensures graceful SIGTERM termination with ProcessLookupError suppression.
    """
    with patch("os.kill") as mock_kill:
        mock_kill.side_effect = [None, ProcessLookupError]
        count = _terminate_pids([101, 102])
        assert count == 1


def test_build_ssh_tunnel_cmd() -> None:
    """Verify _build_ssh_tunnel_cmd builds expected command line options.

    Notes/Architectural Intent:
        Validates port mapping, private key inclusion, and zero-trust flags.
    """
    cmd = _build_ssh_tunnel_cmd(
        host="1.2.3.4",
        port=8000,
        remote_port=8000,
        user="ubuntu",
        key="/fake/key.pem",
        ssh_port=2222,
    )
    assert "-L" in cmd
    assert "8000:localhost:8000" in cmd
    assert "-i" in cmd
    assert "-p" in cmd
    assert "2222" in cmd
    assert "ubuntu@1.2.3.4" in cmd


def test_build_ssh_remote_sync_cmd() -> None:
    """Verify _build_ssh_remote_sync_cmd constructs git pull and uv sync pipeline.

    Notes/Architectural Intent:
        Ensures idempotent pull, hard reset, and uv sync script format.
    """
    cmd = _build_ssh_remote_sync_cmd(
        host="1.2.3.4",
        user="ubuntu",
        key="/fake/key.pem",
        ssh_port=22,
        repo_dir="~/test_dir",
        branch="develop",
    )
    assert "ubuntu@1.2.3.4" in cmd
    remote_script = cmd[-1]
    assert "cd ~/test_dir" in remote_script
    assert "git fetch origin develop" in remote_script
    assert "git reset --hard origin/develop" in remote_script
    assert "uv sync --all-packages --all-extras" in remote_script


def test_resolve_cluster_endpoint() -> None:
    """Verify _resolve_cluster_endpoint prioritizes explicit URL over profile.

    Notes/Architectural Intent:
        Verifies CLI option precedence over profile defaults.
    """
    dummy_runner = HexaqueueProfileConfig(
        server_url="http://profile-url:8000", host="profile-host"
    )
    with (
        patch("hexaqueue_cli.commands.cluster.load_project_config"),
        patch(
            "hexaqueue_cli.commands.cluster.resolve_runner_config",
            return_value=dummy_runner,
        ),
    ):
        url, host = _resolve_cluster_endpoint(profile="ci", explicit_url=None)
        assert url == "http://profile-url:8000"
        assert host == "profile-host"

        override_url, override_host = _resolve_cluster_endpoint(
            profile="ci", explicit_url="http://custom:9000"
        )
        assert override_url == "http://custom:9000"
        assert override_host == "profile-host"


def test_cluster_status_healthy_table() -> None:
    """Verify 'hq cluster status' renders Rich table when controller is online.

    Notes/Architectural Intent:
        Validates operator dashboard output for healthy status.
    """
    with patch(
        "hexaqueue_cli.commands.cluster._probe_health",
        return_value=(True, {"timestamp": "2026-11-02T12:00:00Z"}, 15.2),
    ):
        result = runner.invoke(app, ["cluster", "status"])
        exit_code = result.exit_code
        output = result.output
        assert exit_code == 0
        assert "ONLINE" in output
        assert "Latency" in output


def test_cluster_status_unreachable_exit_1() -> None:
    """Verify 'hq cluster status' returns exit code 1 when controller is unreachable.

    Notes/Architectural Intent:
        Ensures scriptable failure detection for offline controllers.
    """
    with patch(
        "hexaqueue_cli.commands.cluster._probe_health",
        return_value=(False, None, 0.0),
    ):
        result = runner.invoke(app, ["cluster", "status"])
        exit_code = result.exit_code
        output = result.output
        assert exit_code == 1
        assert "Hexaqueue Controller Unreachable" in output


def test_cluster_status_json_format() -> None:
    """Verify 'hq cluster status --format json' outputs valid JSON.

    Notes/Architectural Intent:
        Validates machine-readable structured output format for CI and automation.
    """
    with patch(
        "hexaqueue_cli.commands.cluster._probe_health",
        return_value=(True, {"status": "ok"}, 10.0),
    ):
        result = runner.invoke(app, ["cluster", "status", "--format", "json"])
        exit_code = result.exit_code
        assert exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["healthy"] is True
        assert parsed["latency_ms"] == 10.0


def test_cluster_status_yaml_format_unreachable() -> None:
    """Verify 'hq cluster status --format yaml' outputs YAML and exits with code 1 when down.

    Notes/Architectural Intent:
        Ensures non-zero exit code accompanies structured error states.
    """
    with patch(
        "hexaqueue_cli.commands.cluster._probe_health",
        return_value=(False, None, 0.0),
    ):
        result = runner.invoke(app, ["cluster", "status", "--format", "yaml"])
        exit_code = result.exit_code
        assert exit_code == 1
        assert "healthy: false" in result.output


def test_cluster_ping_success() -> None:
    """Verify 'hq cluster ping' prints latency and returns 0 when healthy.

    Notes/Architectural Intent:
        Verifies fast ping latency probes.
    """
    with patch(
        "hexaqueue_cli.commands.cluster._probe_health",
        return_value=(True, None, 8.42),
    ):
        result = runner.invoke(
            app, ["cluster", "ping", "--url", "http://127.0.0.1:8000"]
        )
        exit_code = result.exit_code
        output = result.output
        assert exit_code == 0
        assert "8.42 ms" in output


def test_cluster_ping_failure() -> None:
    """Verify 'hq cluster ping' exits 1 when probe fails.

    Notes/Architectural Intent:
        Verifies ping error handling.
    """
    with patch(
        "hexaqueue_cli.commands.cluster._probe_health",
        return_value=(False, None, 0.0),
    ):
        result = runner.invoke(
            app, ["cluster", "ping", "--url", "http://127.0.0.1:8000"]
        )
        exit_code = result.exit_code
        assert exit_code == 1
        assert "Could not connect" in result.output


def test_cluster_tunnel_stop_existing() -> None:
    """Verify 'hq cluster tunnel --stop' kills active tunnel processes.

    Notes/Architectural Intent:
        Ensures clean teardown of background SSH forwarding processes.
    """
    with (
        patch(
            "hexaqueue_cli.commands.cluster._find_ssh_tunnel_pids", return_value=[999]
        ),
        patch("hexaqueue_cli.commands.cluster._terminate_pids", return_value=1),
    ):
        result = runner.invoke(app, ["cluster", "tunnel", "--stop", "--port", "8000"])
        exit_code = result.exit_code
        assert exit_code == 0
        assert "Terminated 1 SSH tunnel" in result.output


def test_cluster_tunnel_stop_none_found() -> None:
    """Verify 'hq cluster tunnel --stop' warns when no matching tunnel processes exist.

    Notes/Architectural Intent:
        Ensures idempotent tunnel stop behavior.
    """
    with patch("hexaqueue_cli.commands.cluster._find_ssh_tunnel_pids", return_value=[]):
        result = runner.invoke(app, ["cluster", "tunnel", "--stop", "--port", "8000"])
        exit_code = result.exit_code
        assert exit_code == 0
        assert "No active SSH tunnel found" in result.output


def test_cluster_tunnel_missing_host() -> None:
    """Verify 'hq cluster tunnel' exits with code 1 if target host cannot be resolved.

    Notes/Architectural Intent:
        Validates required configuration validation before spawning subprocess.
    """
    dummy_runner = HexaqueueProfileConfig(host=None)
    with (
        patch("hexaqueue_cli.commands.cluster.load_project_config"),
        patch(
            "hexaqueue_cli.commands.cluster.resolve_runner_config",
            return_value=dummy_runner,
        ),
        patch.dict("os.environ", {}, clear=True),
    ):
        result = runner.invoke(app, ["cluster", "tunnel"])
        exit_code = result.exit_code
        assert exit_code == 1
        assert "Target host not specified" in result.output


def test_cluster_tunnel_already_healthy() -> None:
    """Verify 'hq cluster tunnel' exits early if local port is already healthy.

    Notes/Architectural Intent:
        Prevents redundant SSH tunnel processes when port is already forwarded.
    """
    dummy_runner = HexaqueueProfileConfig(host="1.2.3.4")
    with (
        patch("hexaqueue_cli.commands.cluster.load_project_config"),
        patch(
            "hexaqueue_cli.commands.cluster.resolve_runner_config",
            return_value=dummy_runner,
        ),
        patch(
            "hexaqueue_cli.commands.cluster._probe_health",
            return_value=(True, {"status": "ok"}, 5.0),
        ),
    ):
        result = runner.invoke(app, ["cluster", "tunnel"])
        exit_code = result.exit_code
        assert exit_code == 0
        assert "already connected and healthy" in result.output


def test_cluster_tunnel_success() -> None:
    """Verify 'hq cluster tunnel' launches SSH and polls health until verified.

    Notes/Architectural Intent:
        Validates the happy path of background SSH tunnel creation.
    """
    dummy_runner = HexaqueueProfileConfig(host="1.2.3.4", ssh_user="ubuntu")
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stderr = ""

    with (
        patch("hexaqueue_cli.commands.cluster.load_project_config"),
        patch(
            "hexaqueue_cli.commands.cluster.resolve_runner_config",
            return_value=dummy_runner,
        ),
        patch(
            "hexaqueue_cli.commands.cluster._probe_health",
            return_value=(False, None, 0.0),
        ),
        patch("subprocess.run", return_value=mock_proc),
        patch(
            "hexaqueue_cli.commands.cluster._poll_health",
            return_value=(True, {"status": "ok"}, 18.0),
        ),
    ):
        result = runner.invoke(app, ["cluster", "tunnel", "--port", "8000"])
        exit_code = result.exit_code
        assert exit_code == 0
        assert "Secure SSH Tunnel Established" in result.output


def test_cluster_tunnel_ssh_cmd_error() -> None:
    """Verify 'hq cluster tunnel' exits 1 when SSH subprocess exits non-zero.

    Notes/Architectural Intent:
        Ensures SSH client errors (e.g. key permissions, port bind failure) are surfaced.
    """
    dummy_runner = HexaqueueProfileConfig(host="1.2.3.4")
    mock_proc = MagicMock()
    mock_proc.returncode = 255
    mock_proc.stderr = "Permission denied (publickey)"

    with (
        patch("hexaqueue_cli.commands.cluster.load_project_config"),
        patch(
            "hexaqueue_cli.commands.cluster.resolve_runner_config",
            return_value=dummy_runner,
        ),
        patch(
            "hexaqueue_cli.commands.cluster._probe_health",
            return_value=(False, None, 0.0),
        ),
        patch("subprocess.run", return_value=mock_proc),
    ):
        result = runner.invoke(app, ["cluster", "tunnel"])
        exit_code = result.exit_code
        assert exit_code == 1
        assert "SSH tunnel command failed" in result.output


def test_cluster_sync_missing_host() -> None:
    """Verify 'hq cluster sync' exits with code 1 if target host is unspecified.

    Notes/Architectural Intent:
        Validates argument checks before attempting SSH connection.
    """
    dummy_runner = HexaqueueProfileConfig(host=None)
    with (
        patch("hexaqueue_cli.commands.cluster.load_project_config"),
        patch(
            "hexaqueue_cli.commands.cluster.resolve_runner_config",
            return_value=dummy_runner,
        ),
        patch.dict("os.environ", {}, clear=True),
    ):
        result = runner.invoke(app, ["cluster", "sync"])
        exit_code = result.exit_code
        assert exit_code == 1
        assert "Target host not specified" in result.output


def test_cluster_sync_success() -> None:
    """Verify 'hq cluster sync' invokes SSH git sync command successfully.

    Notes/Architectural Intent:
        Validates remote update orchestration for remote clusters.
    """
    dummy_runner = HexaqueueProfileConfig(host="1.2.3.4", ssh_user="ubuntu")
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "HEAD is now at 1234567\nResolved 50 packages in 2ms"

    with (
        patch("hexaqueue_cli.commands.cluster.load_project_config"),
        patch(
            "hexaqueue_cli.commands.cluster.resolve_runner_config",
            return_value=dummy_runner,
        ),
        patch("subprocess.run", return_value=mock_proc),
    ):
        result = runner.invoke(app, ["cluster", "sync"])
        exit_code = result.exit_code
        assert exit_code == 0
        assert "synchronized successfully" in result.output


def test_cluster_sync_failure() -> None:
    """Verify 'hq cluster sync' exits with code 1 when remote script fails.

    Notes/Architectural Intent:
        Ensures git or uv sync remote errors cause command failure.
    """
    dummy_runner = HexaqueueProfileConfig(host="1.2.3.4")
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stderr = "fatal: not a git repository"

    with (
        patch("hexaqueue_cli.commands.cluster.load_project_config"),
        patch(
            "hexaqueue_cli.commands.cluster.resolve_runner_config",
            return_value=dummy_runner,
        ),
        patch("subprocess.run", return_value=mock_proc),
    ):
        result = runner.invoke(app, ["cluster", "sync"])
        exit_code = result.exit_code
        assert exit_code == 1
        assert "Remote synchronization failed" in result.output
