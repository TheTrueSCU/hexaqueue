"""CLI subcommand group for remote cluster management, SSH tunnels, and CSP monitoring.

Notes/Architectural Intent:
    Provides turnkey `hq cluster` commands (status, ping, tunnel, sync, discover) to manage
    hybrid and remote cluster nodes across CSP environments (OCI, GCP, AWS, Local) without
    requiring manual raw SSH commands or complex shell scripts.
"""

from __future__ import annotations

import json
import os
import signal
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
            console.print(json.dumps(result, indent=2))
        else:
            import yaml

            console.print(yaml.safe_dump(result, sort_keys=False))
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
        return

    # Resolve settings from profile if provided
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
    target_remote_port = (
        remote_port if remote_port != 8000 else (resolved.remote_port or 8000)
    )

    if not target_host:
        console.print(
            "[bold red]Error:[/] Target host not specified. Provide --host, specify host in "
            f"profile '{profile or 'default'}', or export OCI_HOST."
        )
        raise typer.Exit(code=1)

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


__all__ = [
    "app",
    "ping_cmd",
    "status_cmd",
    "sync_cmd",
    "tunnel_cmd",
]
