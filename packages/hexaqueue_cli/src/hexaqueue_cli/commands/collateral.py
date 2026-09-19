"""CLI subcommand group for collateral and artifact management.

Notes/Architectural Intent:
    Provides `hq collateral push` command to stage, register, and compute
    cryptographic digests for job assets, maintaining parity with REST and
    Web Dashboard collateral upload endpoints.
"""

import asyncio
import hashlib
from pathlib import Path

import typer
from rich.console import Console

from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_core.domain.collateral import CollateralKind, CollateralTier

app = typer.Typer(
    name="collateral",
    help="Manage, stage, and inspect collateral artifacts and binaries",
    no_args_is_help=True,
)
console = Console()


@app.command("push")
def push_collateral_cmd(
    file_path: Path = typer.Argument(
        ...,
        help="Path to local collateral file or bundle to stage",
        exists=True,
        readable=True,
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        help="Override logical collateral name (defaults to filename)",
    ),
    tier: str = typer.Option(
        "TEMPORARY",
        "--tier",
        help="Collateral retention tier (TEMPORARY, PERMANENT)",
    ),
    kind: str = typer.Option(
        "BUNDLE",
        "--kind",
        help="Collateral kind (BUNDLE, OS_IMAGE, CONTAINER_IMAGE, TEST_BINARY, DATASET)",
    ),
    user: str = typer.Option(
        "default",
        "--user",
        "-u",
        help="Submitting user identity",
    ),
    admin: bool = typer.Option(
        False,
        "--admin",
        help="Assert explicit administrative elevation",
    ),
) -> None:
    """Stage and register a collateral artifact for compute execution.

    Args:
        file_path: Local file path to stage.
        name: Logical name override.
        tier: Retention tier string.
        kind: Collateral classification kind.
        user: Submitting user identity.
        admin: Administrative elevation flag.

    Notes/Architectural Intent:
        Calculates cryptographic SHA-256 digest and stages metadata through
        the unified execution pipeline.
    """
    content = file_path.read_bytes()
    sha256_hash = hashlib.sha256(content).hexdigest()
    size_bytes = len(content)
    asset_name = name or file_path.name

    resolved_tier = CollateralTier(tier.upper())
    resolved_kind = CollateralKind(kind.upper())

    async def _push() -> None:
        client = LocalClientAdapter()
        try:
            bundle = await client.register_collateral(
                name=asset_name,
                size_bytes=size_bytes,
                checksum_sha256=sha256_hash,
                tier=resolved_tier,
                kind=resolved_kind,
                user_id=user,
                elevate=admin,
            )
            console.print(
                f"[bold green]✓[/] Collateral staged successfully as '[bold cyan]{bundle.id}[/]'"
            )
            console.print(f"  Name:     {bundle.filename}")
            console.print(f"  Checksum: {bundle.sha256_checksum}")
            console.print(f"  Size:     {bundle.size_bytes} bytes")
            console.print(f"  Tier:     {bundle.tier.value}")
        except Exception as exc:
            console.print(f"[bold red]Error staging collateral:[/] {exc}")
            raise typer.Exit(code=1) from exc

    asyncio.run(_push())


__all__ = [
    "app",
]
