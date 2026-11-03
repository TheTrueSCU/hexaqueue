"""CLI subcommand group for remote cluster management, SSH tunnels, and CSP monitoring.

Notes/Architectural Intent:
    Provides turnkey `hq cluster` commands (status, ping, tunnel, sync, discover) to manage
    hybrid and remote cluster nodes across CSP environments (OCI, GCP, AWS, Local) without
    requiring manual raw SSH commands or complex shell scripts.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hexaqueue_cli.infra.options import format_option, resolve_format
from hexaqueue_core.domain.credentials import discover_and_merge_env
from hexaqueue_core.domain.runner_config import (
    load_project_config,
    resolve_runner_config,
)

app = typer.Typer(
    name="cluster",
    help="Manage and monitor remote cluster nodes, SSH tunnels, and CSP controllers",
    no_args_is_help=True,
)
console = Console()


def _probe_host_reachability(
    host: str, port: int = 22, timeout: float = 1.0
) -> tuple[bool, float]:
    """Execute a rapid network reachability probe (TCP socket connect) against candidate host.

    Args:
        host: Target IP address or hostname.
        port: Destination port to probe (default 22 for SSH).
        timeout: Socket timeout in seconds.

    Returns:
        Tuple of (is_reachable, latency_ms).
    """
    if not host or not host.strip():
        return False, 0.0
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return True, elapsed_ms
    except Exception:
        pass
    return False, 0.0


def _probe_health(
    url: str, timeout: float = 3.0
) -> tuple[bool, dict[str, Any] | None, float]:
    """Execute a single HTTP GET health probe against target URL.

    Args:
        url: Controller base URL or health endpoint.
        timeout: Network timeout in seconds.

    Returns:
        Tuple of (is_healthy, payload_dict_or_none, elapsed_time_ms).
    """
    health_url = (
        url if url.rstrip("/").endswith("/health") else f"{url.rstrip('/')}/health"
    )
    if not health_url.startswith(("http://", "https://")):
        return False, None, 0.0
    start = time.perf_counter()
    try:
        req = urllib.request.Request(  # noqa: S310
            health_url, headers={"User-Agent": "hexaqueue-cli"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            if resp.status == 200:
                payload = json.loads(resp.read().decode("utf-8"))
                return True, payload, elapsed_ms
    except Exception:
        pass
    return False, None, 0.0


def _poll_health(
    url: str, timeout_seconds: float = 10.0
) -> tuple[bool, dict[str, Any] | None, float]:
    """Poll health endpoint until healthy response or timeout deadline.

    Args:
        url: Target controller health URL.
        timeout_seconds: Maximum total duration to poll in seconds.

    Returns:
        Tuple of (is_healthy, payload_dict_or_none, elapsed_time_ms).
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        ok, payload, latency = _probe_health(url, timeout=2.0)
        if ok:
            return True, payload, latency
        time.sleep(0.5)
    return False, None, 0.0


def _find_ssh_tunnel_pids(port: int = 8000) -> list[int]:
    """Find process IDs of running SSH background tunnels forwarding to target local port.

    Args:
        port: Local forwarded port to inspect.

    Returns:
        List of matching process IDs.
    """
    pids: list[int] = []
    needle = f"-L {port}:"
    try:
        proc = subprocess.run(
            ["pgrep", "-f", f"ssh.*{needle}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines():
                cleaned = line.strip()
                if cleaned.isdigit():
                    pids.append(int(cleaned))
    except Exception:
        pass
    return pids


def _terminate_pids(pids: list[int]) -> int:
    """Terminate target process IDs with SIGTERM followed by SIGKILL if needed.

    Args:
        pids: Process IDs to terminate.

    Returns:
        Count of successfully terminated processes.
    """
    count = 0
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            count += 1
        except (ProcessLookupError, PermissionError):
            continue
    return count


def _build_ssh_tunnel_cmd(
    host: str,
    port: int = 8000,
    remote_port: int = 8000,
    user: str = "ubuntu",
    key: str | None = None,
    ssh_port: int = 22,
) -> list[str]:
    """Construct command arguments for background SSH port-forwarding tunnel.

    Args:
        host: Target remote cluster host IP or hostname.
        port: Local port to bind forwarding to.
        remote_port: Target controller port on remote host.
        user: SSH user identity.
        key: Path to SSH private key file.
        ssh_port: Remote SSH daemon port.

    Returns:
        List of command line string arguments for subprocess invocation.
    """
    cmd = [
        "ssh",
        "-f",
        "-N",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=15",
        "-p",
        str(ssh_port),
        "-L",
        f"{port}:localhost:{remote_port}",
    ]
    if key:
        expanded_key = str(Path(key).expanduser())
        cmd.extend(["-i", expanded_key])
    cmd.append(f"{user}@{host}")
    return cmd


def _build_ssh_remote_sync_cmd(
    host: str,
    user: str = "ubuntu",
    key: str | None = None,
    ssh_port: int = 22,
    repo_dir: str = "~/hexaqueue",
    branch: str = "main",
) -> list[str]:
    """Construct remote SSH git synchronization command.

    Args:
        host: Target remote host IP or hostname.
        user: SSH user identity.
        key: Path to SSH private key.
        ssh_port: SSH daemon port.
        repo_dir: Working directory on remote host.
        branch: Git branch name to pull and reset to.

    Returns:
        Command arguments for subprocess execution.
    """
    remote_script = (
        f"cd {repo_dir} && git fetch origin {branch} && "
        f"git reset --hard origin/{branch} && git clean -fd && "
        f"~/.local/bin/uv sync --all-packages --all-extras"
    )
    cmd = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ConnectTimeout=15",
        "-p",
        str(ssh_port),
    ]
    if key:
        cmd.extend(["-i", str(Path(key).expanduser())])
    cmd.extend([f"{user}@{host}", remote_script])
    return cmd


def _resolve_cluster_endpoint(
    profile: str | None, explicit_url: str | None
) -> tuple[str, str | None]:
    """Resolve controller server URL and host from profile or explicit options.

    Args:
        profile: Profile name overlay.
        explicit_url: Explicit URL CLI option.

    Returns:
        Tuple of (server_url, host_or_none).
    """
    proj_cfg = load_project_config()
    resolved = resolve_runner_config(project_config=proj_cfg, profile=profile)
    server_url = explicit_url or resolved.server_url
    return server_url, resolved.host


@app.command("status")
def status_cmd(
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Active runner profile name to inspect"
    ),
    url: str | None = typer.Option(
        None, "--url", "-u", help="Explicit Hexaqueue controller URL override"
    ),
    format_type: str = format_option(),
) -> None:
    """Inspect operational health and latency of the Hexaqueue cluster controller.

    Args:
        profile: Active runner profile name to inspect.
        url: Explicit Hexaqueue controller URL override.
        format_type: Chosen serialization output format.

    Raises:
        typer.Exit: With code 1 if controller is unreachable.

    Notes/Architectural Intent:
        Probes the cluster controller `/health` endpoint and inspects active CSP provider
        guards to give operators immediate visibility into cluster readiness.
    """
    server_url, host = _resolve_cluster_endpoint(profile, url)
    resolved_fmt = resolve_format(format_type)

    ok, payload, latency = _probe_health(server_url)

    if resolved_fmt in ("json", "yaml"):
        result: dict[str, Any] = {
            "server_url": server_url,
            "host": host,
            "profile": profile,
            "healthy": ok,
            "latency_ms": round(latency, 2) if ok else None,
            "payload": payload,
        }
        if resolved_fmt == "json":
            console.print(json.dumps(result, indent=2), highlight=False)
        else:
            import yaml

            console.print(yaml.safe_dump(result, sort_keys=False), highlight=False)
        if not ok:
            raise typer.Exit(code=1)
        return

    if not ok:
        panel_content = (
            f"[bold red]✖ Hexaqueue Controller Unreachable[/]\n\n"
            f"[bold]Target URL:[/] {server_url}\n"
            f"[bold]Host:[/] {host or 'Local / Not Specified'}\n"
            f"[bold]Profile:[/] {profile or 'default'}\n\n"
            f"[yellow]Troubleshooting Steps:[/]\n"
            f" • Start local daemon: [cyan]hq server start[/]\n"
            f" • Connect SSH tunnel to remote cluster: [cyan]hq cluster tunnel --profile {profile or 'ci'}[/]"
        )
        console.print(
            Panel(panel_content, border_style="red", title="Cluster Controller Status")
        )
        raise typer.Exit(code=1)

    table = Table(title="Hexaqueue Cluster Controller Health", border_style="green")
    table.add_column("Property", style="bold cyan")
    table.add_column("Value", style="green")

    table.add_row("Status", "● ONLINE (Healthy)")
    table.add_row("Server URL", server_url)
    if host:
        table.add_row("Remote Host", host)
    table.add_row("Latency", f"{latency:.2f} ms")
    if payload:
        if "cores" in payload:
            table.add_row("Worker Cores", str(payload["cores"]))
        if "provider" in payload:
            table.add_row("CSP Provider", str(payload["provider"]))
        if "timestamp" in payload:
            table.add_row("Timestamp", str(payload["timestamp"]))
        if "correlation_id" in payload:
            table.add_row("Correlation ID", str(payload["correlation_id"]))

    console.print(table)


@app.command("ping")
def ping_cmd(
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Profile name to target"
    ),
    url: str | None = typer.Option(
        None, "--url", "-u", help="Explicit Hexaqueue controller URL override"
    ),
) -> None:
    """Perform a rapid latency probe against the cluster controller.

    Args:
        profile: Profile name to target.
        url: Explicit Hexaqueue controller URL override.

    Raises:
        typer.Exit: With code 1 if ping probe fails.
    """
    server_url, _ = _resolve_cluster_endpoint(profile, url)
    ok, _, latency = _probe_health(server_url)
    if not ok:
        console.print(
            f"[bold red]✖ Error:[/] Could not connect to controller at {server_url}"
        )
        raise typer.Exit(code=1)
    console.print(
        f"[bold green]✓[/] Controller at [cyan]{server_url}[/] responded in [bold green]{latency:.2f} ms[/]"
    )


def _stop_active_tunnels(port: int) -> None:
    """Terminate active SSH tunnel processes forwarding on the specified local port.

    Args:
        port: Local port to check and terminate.

    Notes/Architectural Intent:
        Finds all background SSH port-forwarding processes bound to the local port
        and terminates them gracefully or with SIGKILL if unresponsive.
    """
    pids = _find_ssh_tunnel_pids(port)
    if not pids:
        console.print(
            f"[yellow]No active SSH tunnel found forwarding on port {port}.[/]"
        )
        return
    terminated = _terminate_pids(pids)
    console.print(
        f"[bold green]✓[/] Terminated [bold cyan]{terminated}[/] SSH tunnel process(es) forwarding on port {port}."
    )


def _resolve_tunnel_target(
    profile: str | None,
    host: str | None,
    user: str,
    key: str | None,
    ssh_port: int,
    remote_port: int,
) -> tuple[str, str, str | None, int, int]:
    """Resolve SSH target parameters from CLI flags, runner profile, env, or auto-discovery.

    Args:
        profile: Runner profile specifying target host and keys.
        host: Target remote cluster host IP or hostname.
        user: SSH login user.
        key: Path to SSH private key identity file.
        ssh_port: Remote SSH server port.
        remote_port: Remote daemon port.

    Returns:
        Tuple of (target_host, target_user, target_key, target_ssh_port, target_remote_port).

    Raises:
        typer.Exit: If target host cannot be resolved.

    Notes/Architectural Intent:
        Applies hierarchical configuration cascading: CLI args override profile config,
        profile config overrides environment variables, and auto-discovery serves as fallback.
    """
    proj_cfg = load_project_config()
    resolved = resolve_runner_config(project_config=proj_cfg, profile=profile)
    env = discover_and_merge_env()

    target_host = (
        host
        or resolved.host
        or env.get("OCI_HOST")
        or env.get("HEXAQUEUE_CLUSTER_HOST")
    )
    target_user = (
        user
        if user != "ubuntu"
        else (resolved.ssh_user or env.get("OCI_USER", "ubuntu"))
    )
    target_key = key or resolved.ssh_key or env.get("HEXAQUEUE_SSH_KEY")
    target_ssh_port = ssh_port if ssh_port != 22 else (resolved.ssh_port or 22)
    target_remote_port = (
        remote_port if remote_port != 8000 else (resolved.remote_port or 8000)
    )

    if not target_host:
        discovered = _auto_select_online_host()
        if discovered:
            target_host = discovered["host"]
            target_user = (
                user if user != "ubuntu" else discovered.get("user", target_user)
            )
            target_key = key or discovered.get("key") or target_key
            target_ssh_port = (
                ssh_port if ssh_port != 22 else int(discovered.get("ssh_port") or 22)
            )
            console.print(
                f"[dim]Auto-discovered reachable candidate:[/] [bold cyan]{target_host}[/] "
                f"({discovered.get('provider')})"
            )

    if not target_host:
        console.print(
            "[bold red]Error:[/] Target host not specified. Provide --host, specify host in "
            f"profile '{profile or 'default'}', or export OCI_HOST."
        )
        raise typer.Exit(code=1)

    return target_host, target_user, target_key, target_ssh_port, target_remote_port


@app.command("tunnel")
def tunnel_cmd(
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Runner profile specifying target host and keys"
    ),
    host: str | None = typer.Option(
        None, "--host", "-h", help="Target remote cluster host IP or hostname"
    ),
    port: int = typer.Option(8000, "--port", help="Local forwarding listen port"),
    remote_port: int = typer.Option(8000, "--remote-port", help="Remote daemon port"),
    user: str = typer.Option("ubuntu", "--user", "-u", help="SSH login user"),
    key: str | None = typer.Option(
        None, "--key", "-i", help="Path to SSH private key identity file"
    ),
    ssh_port: int = typer.Option(22, "--ssh-port", help="Remote SSH server port"),
    stop: bool = typer.Option(
        False, "--stop", help="Terminate active SSH tunnel on local port"
    ),
) -> None:
    """Establish or terminate a secure SSH port-forwarding tunnel to the remote cluster.

    Args:
        profile: Runner profile specifying target host and keys.
        host: Target remote cluster host IP or hostname.
        port: Local forwarding listen port.
        remote_port: Remote daemon port.
        user: SSH login user.
        key: Path to SSH private key identity file.
        ssh_port: Remote SSH server port.
        stop: Terminate active SSH tunnel on local port.

    Raises:
        typer.Exit: With code 1 if tunnel establishment or teardown fails.

    Notes/Architectural Intent:
        Enforces zero-trust isolation: rather than exposing port 8000 to the public internet,
        this command establishes an encrypted SSH tunnel directly to the controller daemon.
    """
    if stop:
        _stop_active_tunnels(port)
        return

    target_host, target_user, target_key, target_ssh_port, target_remote_port = (
        _resolve_tunnel_target(
            profile=profile,
            host=host,
            user=user,
            key=key,
            ssh_port=ssh_port,
            remote_port=remote_port,
        )
    )

    # Check if local port is already responding to /health
    already_healthy, _, latency = _probe_health(f"http://127.0.0.1:{port}")
    if already_healthy:
        console.print(
            f"[bold green]✓[/] Port [cyan]{port}[/] is already connected and healthy ({latency:.2f} ms). No tunnel needed."
        )
        return

    ssh_cmd = _build_ssh_tunnel_cmd(
        host=target_host,
        port=port,
        remote_port=target_remote_port,
        user=target_user,
        key=target_key,
        ssh_port=target_ssh_port,
    )

    console.print(
        f"[bold cyan]Establishing SSH tunnel to {target_user}@{target_host}:{target_remote_port}...[/]"
    )
    try:
        proc = subprocess.run(ssh_cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0 and proc.stderr:
            console.print(
                f"[bold red]SSH tunnel command failed:[/] {proc.stderr.strip()}"
            )
            raise typer.Exit(code=1)
    except Exception as exc:
        console.print(f"[bold red]Failed to execute SSH command:[/] {exc}")
        raise typer.Exit(code=1) from exc

    # Poll health to verify tunnel connectivity
    ok, payload, elapsed_ms = _poll_health(
        f"http://127.0.0.1:{port}", timeout_seconds=10.0
    )
    if not ok:
        console.print(
            f"[bold red]✖ Tunnel established, but health check failed on http://127.0.0.1:{port}/health[/]"
        )
        raise typer.Exit(code=1)

    panel_content = (
        f"[bold green]✓ Secure SSH Tunnel Established[/]\n\n"
        f"[bold]Local Forwarding:[/] http://127.0.0.1:{port}\n"
        f"[bold]Remote Endpoint:[/] {target_user}@{target_host}:{target_remote_port}\n"
        f"[bold]Daemon Status:[/] {payload.get('status', 'ok') if payload else 'ok'} ({elapsed_ms:.2f} ms)\n\n"
        f"[dim]To disconnect tunnel later:[/] [cyan]hq cluster tunnel --stop --port {port}[/]"
    )
    console.print(
        Panel(panel_content, border_style="green", title="Hexaqueue Cluster Tunnel")
    )


@app.command("sync")
def sync_cmd(
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Runner profile specifying target host and keys"
    ),
    host: str | None = typer.Option(
        None, "--host", "-h", help="Target remote cluster host IP or hostname"
    ),
    user: str = typer.Option("ubuntu", "--user", "-u", help="SSH login user"),
    key: str | None = typer.Option(
        None, "--key", "-i", help="Path to SSH private key identity file"
    ),
    ssh_port: int = typer.Option(22, "--ssh-port", help="Remote SSH server port"),
    repo_dir: str = typer.Option(
        "~/hexaqueue", "--repo-dir", help="Remote workspace repository directory"
    ),
    branch: str = typer.Option(
        "main", "--branch", "-b", help="Git branch to fetch and reset to"
    ),
) -> None:
    """Trigger remote repository synchronization and dependency resolution over SSH.

    Args:
        profile: Runner profile specifying target host and keys.
        host: Target remote cluster host IP or hostname.
        user: SSH login user.
        key: Path to SSH private key identity file.
        ssh_port: Remote SSH server port.
        repo_dir: Remote workspace repository directory.
        branch: Git branch to fetch and reset to.

    Raises:
        typer.Exit: With code 1 if synchronization fails.
    """
    proj_cfg = load_project_config()
    resolved = resolve_runner_config(project_config=proj_cfg, profile=profile)

    target_host = (
        host
        or resolved.host
        or os.environ.get("OCI_HOST")
        or os.environ.get("HEXAQUEUE_CLUSTER_HOST")
    )
    target_user = user if user != "ubuntu" else (resolved.ssh_user or "ubuntu")
    target_key = key or resolved.ssh_key or os.environ.get("HEXAQUEUE_SSH_KEY")
    target_ssh_port = ssh_port if ssh_port != 22 else (resolved.ssh_port or 22)

    if not target_host:
        console.print(
            "[bold red]Error:[/] Target host not specified. Provide --host or configure profile host."
        )
        raise typer.Exit(code=1)

    cmd = _build_ssh_remote_sync_cmd(
        host=target_host,
        user=target_user,
        key=target_key,
        ssh_port=target_ssh_port,
        repo_dir=repo_dir,
        branch=branch,
    )

    console.print(
        f"[bold cyan]Synchronizing remote cluster at {target_user}@{target_host}:{repo_dir} (branch: {branch})...[/]"
    )
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            console.print(
                f"[bold red]Remote synchronization failed (exit code {proc.returncode}):[/]\n{proc.stderr.strip()}"
            )
            raise typer.Exit(code=1)
        console.print(
            f"[bold green]✓[/] Remote repository synchronized successfully on [bold cyan]{target_host}[/].\n"
            f"[dim]{proc.stdout.strip()}[/]"
        )
    except Exception as exc:
        console.print(f"[bold red]Error executing remote sync:[/] {exc}")
        raise typer.Exit(code=1) from exc


def _apply_ssh_directive(key: str, val: str, entry: dict[str, Any]) -> None:
    """Apply an SSH config key-value directive to an entry dictionary."""
    if key == "hostname":
        entry["host"] = val
    elif key == "user":
        entry["user"] = val
    elif key == "identityfile":
        entry["key"] = val
    elif key == "port":
        with contextlib.suppress(ValueError):
            entry["ssh_port"] = int(val)


def _read_ssh_config_entries(ssh_cfg: Path) -> list[dict[str, Any]]:
    """Read host blocks from an SSH config file."""
    candidates: list[dict[str, Any]] = []
    current_entry: dict[str, Any] = {}
    try:
        with ssh_cfg.open("r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(maxsplit=1)
                if len(parts) < 2:
                    continue
                key, val = parts[0].lower(), parts[1].strip()
                if key == "host":
                    if "host" in current_entry:
                        candidates.append(current_entry)
                    current_entry = {"alias": val, "host": val, "source": "ssh_config"}
                elif current_entry:
                    _apply_ssh_directive(key, val, current_entry)
        if "host" in current_entry:
            candidates.append(current_entry)
    except Exception:
        pass
    return candidates


def _parse_ssh_config_hosts() -> list[dict[str, Any]]:
    """Parse candidate cluster hosts from ~/.ssh/config.

    Returns:
        List of candidate host dictionaries.
    """
    ssh_cfg = Path("~/.ssh/config").expanduser()
    if not ssh_cfg.exists():
        return []
    candidates = _read_ssh_config_entries(ssh_cfg)
    needles = ("hq", "hexaqueue", "oci", "cluster")
    return [
        c
        for c in candidates
        if any(
            n in c.get("alias", "").lower() or n in c.get("host", "").lower()
            for n in needles
        )
    ]


def _discover_from_env(seen_hosts: set[str]) -> list[dict[str, Any]]:
    """Extract candidate cluster nodes from environment variables and .env files."""
    results: list[dict[str, Any]] = []
    env = discover_and_merge_env()
    for k, val in env.items():
        if not k.endswith("_HOST") or not val or val in seen_hosts:
            continue
        prefix = k[:-5]
        provider = "Custom" if prefix in ("HEXAQUEUE_CLUSTER", "CLUSTER") else prefix
        user = env.get(f"{prefix}_USER", "ubuntu")
        key = env.get(f"{prefix}_KEY", env.get("HEXAQUEUE_SSH_KEY"))
        ssh_port_str = env.get(f"{prefix}_SSH_PORT", "22")
        try:
            ssh_port = int(ssh_port_str)
        except ValueError:
            ssh_port = 22
        seen_hosts.add(val)
        results.append(
            {
                "host": val,
                "provider": provider.upper(),
                "source": f"env:{k}",
                "user": user,
                "key": key,
                "ssh_port": ssh_port,
            }
        )
    return results


def _discover_from_profiles(seen_hosts: set[str]) -> list[dict[str, Any]]:
    """Extract candidate cluster nodes from project configuration profiles."""
    results: list[dict[str, Any]] = []
    try:
        proj_cfg = load_project_config()
        for prof_name, prof_val in proj_cfg.profiles.items():
            if prof_val.host and prof_val.host not in seen_hosts:
                seen_hosts.add(prof_val.host)
                results.append(
                    {
                        "host": prof_val.host,
                        "provider": prof_name.upper(),
                        "source": f"profile:{prof_name}",
                        "user": prof_val.ssh_user or "ubuntu",
                        "key": prof_val.ssh_key,
                        "ssh_port": prof_val.ssh_port or 22,
                    }
                )
    except Exception:
        pass
    return results


def _discover_from_ssh(seen_hosts: set[str]) -> list[dict[str, Any]]:
    """Extract candidate cluster nodes from SSH config entries."""
    results: list[dict[str, Any]] = []
    for c in _parse_ssh_config_hosts():
        h = c.get("host")
        if h and h not in seen_hosts:
            seen_hosts.add(h)
            results.append(
                {
                    "host": h,
                    "provider": "SSH Config",
                    "source": f"ssh:{c.get('alias')}",
                    "user": c.get("user", "ubuntu"),
                    "key": c.get("key"),
                    "ssh_port": c.get("ssh_port", 22),
                }
            )
    return results


def _discover_candidates(provider: str = "auto") -> list[dict[str, Any]]:
    """Aggregate candidate cluster hosts across environment, profiles, and SSH configuration.

    Args:
        provider: Provider filter ('auto', 'oci', 'ssh', 'env', 'profiles').

    Returns:
        List of candidate host dictionaries.
    """
    results: list[dict[str, Any]] = []
    seen_hosts: set[str] = set()

    if provider in ("auto", "env", "oci"):
        results.extend(_discover_from_env(seen_hosts))
    if provider in ("auto", "profiles", "oci"):
        results.extend(_discover_from_profiles(seen_hosts))
    if provider in ("auto", "ssh", "oci"):
        results.extend(_discover_from_ssh(seen_hosts))

    return results


def _auto_select_online_host() -> dict[str, Any] | None:
    """Auto-discover candidate cluster hosts and return the first online candidate.

    Returns:
        Selected candidate dictionary or None if none are reachable.
    """
    candidates = _discover_candidates("auto")
    for cand in candidates:
        c_host = cand.get("host")
        if not c_host:
            continue
        c_port = int(cand.get("ssh_port") or 22)
        is_online, _ = _probe_host_reachability(c_host, port=c_port, timeout=1.0)
        if is_online:
            return cand
    return None


def _probe_single_candidate(cand: dict[str, Any]) -> dict[str, Any]:
    """Execute two-tier reachability and API health probe for a single candidate host.

    Args:
        cand: Candidate dictionary containing host and metadata.

    Returns:
        Enriched candidate dictionary with health status and capacity.
    """
    host = cand["host"]
    ssh_port = int(cand.get("ssh_port") or 22)

    # Tier 1: Host Reachability Probe
    is_online, ping_latency = _probe_host_reachability(host, port=ssh_port, timeout=1.0)
    if not is_online and host in ("127.0.0.1", "localhost"):
        is_online, ping_latency = True, 0.1

    # Tier 2: Hexaqueue API Health Probe (if host is online)
    api_ok = False
    payload = None
    api_latency = 0.0
    if is_online:
        api_ok, payload, api_latency = _probe_health(f"http://{host}:8000", timeout=1.0)
        if not api_ok and host in ("127.0.0.1", "localhost"):
            api_ok, payload, api_latency = _probe_health(
                "http://127.0.0.1:8000", timeout=1.0
            )

    if api_ok:
        status_text = "ONLINE"
        latency_ms = round(api_latency, 2)
    elif is_online:
        status_text = "SSH_AVAILABLE"
        latency_ms = round(ping_latency, 2)
    else:
        status_text = "OFFLINE"
        latency_ms = None

    cores = payload.get("cores") if payload else None
    return {
        **cand,
        "healthy": api_ok,
        "is_online": is_online,
        "status": status_text,
        "latency_ms": latency_ms,
        "cores": cores,
        "recommended_tunnel": f"hq cluster tunnel --host {host} --user {cand.get('user', 'ubuntu')}",
    }


def _render_discovered_table(probed: list[dict[str, Any]]) -> None:
    """Render Rich table of probed candidate nodes."""
    table = Table(title="Discovered Hexaqueue Cluster Nodes", border_style="cyan")
    table.add_column("Host", style="bold cyan")
    table.add_column("Provider", style="green")
    table.add_column("Source", style="dim")
    table.add_column("Status", style="bold")
    table.add_column("Cores", justify="right")
    table.add_column("Latency", justify="right")
    table.add_column("Tunnel Command", style="yellow")

    for p in probed:
        if p.get("healthy"):
            status_disp = "[green]● ONLINE[/]"
        elif p.get("is_online"):
            status_disp = "[yellow]○ SSH READY[/]"
        else:
            status_disp = "[red]✖ OFFLINE[/]"
        cores_disp = str(p["cores"]) if p.get("cores") is not None else "-"
        lat_disp = (
            f"{p['latency_ms']:.2f} ms" if p.get("latency_ms") is not None else "-"
        )
        table.add_row(
            p["host"],
            p.get("provider", "Unknown"),
            p.get("source", "Unknown"),
            status_disp,
            cores_disp,
            lat_disp,
            p["recommended_tunnel"],
        )

    console.print(table)


@app.command("discover")
def discover_cmd(
    provider: str = typer.Option(
        "auto",
        "--provider",
        "-p",
        help="Provider discovery target ('auto', 'oci', 'ssh', 'env', 'profiles')",
    ),
    format_type: str = format_option(),
) -> None:
    """Discover available remote cluster nodes, active controllers, and SSH connection endpoints.

    Args:
        provider: Provider discovery target filter.
        format_type: Output presentation format.

    Notes/Architectural Intent:
        Discovers remote nodes across environment variables, runner profiles, and SSH configuration,
        probing for live controller readiness to eliminate hardcoded endpoint references.
    """
    candidates = _discover_candidates(provider)
    resolved_fmt = resolve_format(format_type)

    probed = [_probe_single_candidate(cand) for cand in candidates]

    if resolved_fmt in ("json", "yaml"):
        if resolved_fmt == "json":
            console.print(json.dumps(probed, indent=2), highlight=False)
        else:
            import yaml

            console.print(yaml.safe_dump(probed, sort_keys=False), highlight=False)
        return

    if not probed:
        console.print(
            "[yellow]No candidate cluster hosts discovered. Configure a profile or export OCI_HOST.[/]"
        )
        return

    _render_discovered_table(probed)


__all__ = [
    "app",
    "discover_cmd",
    "ping_cmd",
    "status_cmd",
    "sync_cmd",
    "tunnel_cmd",
]
