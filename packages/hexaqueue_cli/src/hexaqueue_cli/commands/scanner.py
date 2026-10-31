"""CLI subcommand group for malware scanning, quarantine, and security verification.

Notes/Architectural Intent:
    Provides `hq scanner file`, `hq scanner daemon`, and `hq scanner ping` commands
    to manually inspect files or operate the background security worker daemon.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from hexaqueue_scanner.adapters.clamav import ClamAvDaemonAdapter
from hexaqueue_scanner.adapters.yara import YaraRuleScannerAdapter
from hexaqueue_scanner.domain.config import ScannerConfig
from hexaqueue_scanner.infra.bootstrap import create_scanner_daemon
from hexaqueue_scanner.ports.engine import MalwareScannerEnginePort

app = typer.Typer(
    name="scanner",
    help="Malware inspection, antivirus verification, and quarantine daemon",
    no_args_is_help=True,
)
console = Console()
logger = logging.getLogger(__name__)


@app.command("file")
def scan_file_cmd(
    file_path: Path = typer.Argument(
        ...,
        help="Path to local file or artifact to scan",
        exists=True,
        readable=True,
    ),
    clamav_socket: str = typer.Option(
        "/var/run/clamav/clamd.ctl",
        "--clamav-socket",
        help="Path to ClamAV UNIX domain socket",
    ),
    yara_rule: list[str] | None = typer.Option(
        None,
        "--rule",
        "-r",
        help="Path to YARA rule file (.yar)",
    ),
) -> None:
    """Inspect a local file for virus signatures and YARA heuristic matches.

    Args:
        file_path: Path to target file on disk.
        clamav_socket: ClamAV socket path.
        yara_rule: Optional list of YARA rule paths.

    Notes/Architectural Intent:
        Executes immediate multi-engine scan on local target file without requiring
        a running server or collateral registration.
    """

    async def _run_scan() -> None:
        engines: list[MalwareScannerEnginePort] = []
        if Path(clamav_socket).exists():
            engines.append(
                ClamAvDaemonAdapter(
                    config=ScannerConfig().clamav.model_copy(
                        update={"socket_path": clamav_socket}
                    )
                )
            )

        if yara_rule:
            engines.append(
                YaraRuleScannerAdapter(
                    config=ScannerConfig().yara.model_copy(
                        update={"rule_paths": yara_rule}
                    )
                )
            )

        if not engines:
            # Fallback to local heuristic scanner if no daemons available
            console.print(
                "[yellow]Notice:[/] No active ClamAV socket or YARA rules specified. Using default rule evaluation."
            )
            engines.append(YaraRuleScannerAdapter(config=ScannerConfig().yara))

        console.print(
            f"[bold blue]Scanning[/] {file_path.name} ({file_path.stat().st_size} bytes)..."
        )
        all_clean = True
        table = Table(title=f"Scan Findings: {file_path.name}")
        table.add_column("Scanner Engine", style="cyan")
        table.add_column("Clean?", style="bold")
        table.add_column("Threat / Rule Match", style="red")

        for engine in engines:
            res = await engine.scan_file(file_path)
            status_str = "[green]CLEAN[/]" if res.is_clean else "[red]INFECTED[/]"
            table.add_row(res.scanner_engine, status_str, res.threat_name or "None")
            if not res.is_clean:
                all_clean = False

        console.print(table)
        if all_clean:
            console.print("[bold green]✓ Artifact is verified clean.[/]")
        else:
            console.print("[bold red]✗ Threat detected! Artifact flagged.[/]")
            raise typer.Exit(code=2)

    asyncio.run(_run_scan())


@app.command("daemon")
def run_daemon_cmd(
    poll_interval: float = typer.Option(
        1.0,
        "--poll-interval",
        "-i",
        help="Polling interval in seconds for scan task queue",
    ),
    quarantine_on_threat: bool = typer.Option(
        True,
        "--quarantine/--reject",
        help="Whether to isolate threats in quarantine vault or reject outright",
    ),
) -> None:
    """Run the background security scanner worker daemon.

    Args:
        poll_interval: Loop sleep interval in seconds.
        quarantine_on_threat: Flag to quarantine or reject threats.

    Notes/Architectural Intent:
        Continuously polls for staged collateral bundles, verifies them against
        configured antivirus engines, and promotes or quarantines them.
    """
    config = ScannerConfig(quarantine_on_threat=quarantine_on_threat)
    daemon = create_scanner_daemon(config=config, poll_interval_seconds=poll_interval)

    async def _run() -> None:
        console.print("[bold green]Starting Hexaqueue Security Scanner Daemon...[/]")
        console.print(f"  Poll Interval:       {poll_interval}s")
        console.print(f"  Quarantine On Threat: {quarantine_on_threat}")
        await daemon.start()
        try:
            while daemon.is_running():
                await asyncio.sleep(1.0)
        except (KeyboardInterrupt, asyncio.CancelledError):
            console.print("\n[yellow]Stopping scanner daemon gracefully...[/]")
        finally:
            await daemon.stop()
            metrics = daemon.get_metrics()
            console.print(
                f"[bold cyan]Scanner Daemon Stopped.[/] Processed: {metrics.total_scans} (Clean: {metrics.approved_scans}, Quarantined: {metrics.quarantined_scans}, Rejected: {metrics.rejected_scans})"
            )

    asyncio.run(_run())


@app.command("ping")
def ping_cmd(
    clamav_socket: str = typer.Option(
        "/var/run/clamav/clamd.ctl",
        "--clamav-socket",
        help="Path to ClamAV UNIX domain socket",
    ),
) -> None:
    """Check connectivity and responsiveness of security inspection engines.

    Args:
        clamav_socket: UNIX domain socket path for clamd.
    """

    async def _ping() -> None:
        clamav = ClamAvDaemonAdapter(
            config=ScannerConfig().clamav.model_copy(
                update={"socket_path": clamav_socket}
            )
        )
        is_healthy = await clamav.ping()
        if is_healthy:
            console.print("[bold green]✓ ClamAV daemon is healthy and reachable.[/]")
        else:
            console.print(
                f"[yellow]! ClamAV daemon is unreachable on {clamav_socket} (daemon may be offline).[/]"
            )

    asyncio.run(_ping())


__all__ = [
    "app",
]
