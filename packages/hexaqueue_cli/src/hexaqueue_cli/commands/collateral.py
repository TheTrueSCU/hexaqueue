"""CLI subcommand group for collateral and artifact management.

Notes/Architectural Intent:
    Provides ``hq collateral`` subcommands (``push``/``stage``, ``list``, ``inspect``,
    ``promote``, ``pin``, ``unpin``, ``delete``, ``evict``) backed by ``ClientPort``
    and the unified CQRS pipeline across both local and remote controllers.
"""

import asyncio
import hashlib
import json
from pathlib import Path

import typer
from rich.console import Console

from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_cli.adapters.presenter import CliPresenter
from hexaqueue_cli.infra.options import format_option, resolve_format, url_option
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
    ttl_seconds: int | None = typer.Option(
        None,
        "--ttl",
        min=1,
        help="Optional custom TTL in seconds for TEMPORARY collateral",
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
    url: str | None = url_option(),
) -> None:
    """Stage and register a collateral artifact for compute execution.

    Args:
        file_path: Local file path to stage.
        name: Logical name override.
        tier: Retention tier string.
        kind: Collateral classification kind.
        ttl_seconds: Optional custom TTL in seconds for TEMPORARY collateral.
        user: Submitting user identity.
        admin: Administrative elevation flag.
        url: Optional remote controller base URL.

    Notes/Architectural Intent:
        Calculates cryptographic SHA-256 digest and stages metadata and payload
        through ``ClientPort`` (CQRS locally, or ``/v1/collateral/stage`` remotely).
    """
    content = file_path.read_bytes()
    sha256_hash = hashlib.sha256(content).hexdigest()
    size_bytes = len(content)
    asset_name = name or file_path.name
    if (
        ".." in asset_name
        or "/" in asset_name
        or "\\" in asset_name
        or Path(asset_name).is_absolute()
    ):
        console.print(
            f"[bold red]Error:[/] Collateral name '{asset_name}' contains illegal path components."
        )
        raise typer.Exit(code=1)

    resolved_tier = CollateralTier(tier.upper())
    resolved_kind = CollateralKind(kind.upper())

    async def _push() -> None:
        client = LocalClientAdapter(controller_url=url)
        try:
            bundle = await client.register_collateral(
                name=asset_name,
                size_bytes=size_bytes,
                checksum_sha256=sha256_hash,
                tier=resolved_tier,
                kind=resolved_kind,
                target_path=str(file_path),
                ttl_seconds=ttl_seconds,
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


# Register stage command alias
app.command("stage")(push_collateral_cmd)


@app.command("list")
def list_collateral_cmd(
    user: str = typer.Option(
        "default", "--user", "-u", help="Requesting user identity"
    ),
    admin: bool = typer.Option(
        False,
        "--admin",
        help="Assert explicit administrative elevation to view all owners' collateral",
    ),
    format_type: str = format_option(),
    url: str | None = url_option(),
) -> None:
    """List collateral bundles visible to the requesting identity.

    Args:
        user: Requesting user identity.
        admin: Administrative elevation flag.
        format_type: Output presentation format.
        url: Optional remote controller base URL.

    Notes/Architectural Intent:
        Non-admin callers see only bundles owned by ``user``; elevated callers
        inspect all cluster collateral bundles.
    """
    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)

    async def _list() -> None:
        client = LocalClientAdapter(controller_url=url)
        try:
            bundles = await client.list_collateral(user_id=user, elevate=admin)
            presenter.render_collateral_list(bundles, resolved_fmt)
        except Exception as exc:
            console.print(f"[bold red]Error listing collateral:[/] {exc}")
            raise typer.Exit(code=1) from exc

    asyncio.run(_list())


@app.command("inspect")
def inspect_collateral_cmd(
    collateral_id: str = typer.Argument(..., help="Collateral bundle ID to inspect"),
    user: str = typer.Option(
        "default", "--user", "-u", help="Requesting user identity"
    ),
    admin: bool = typer.Option(
        False,
        "--admin",
        help="Assert explicit administrative elevation",
    ),
    format_type: str = format_option(),
    url: str | None = url_option(),
) -> None:
    """Inspect detailed metadata and URIs for a single collateral bundle.

    Args:
        collateral_id: Target collateral bundle identifier.
        user: Requesting user identity.
        admin: Administrative elevation flag.
        format_type: Output presentation format.
        url: Optional remote controller base URL.
    """
    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)

    async def _inspect() -> None:
        client = LocalClientAdapter(controller_url=url)
        try:
            bundle = await client.get_collateral(
                collateral_id, user_id=user, elevate=admin
            )
            presenter.render_collateral_detail(bundle, resolved_fmt)
        except Exception as exc:
            console.print(
                f"[bold red]Error inspecting collateral '{collateral_id}':[/] {exc}"
            )
            raise typer.Exit(code=1) from exc

    asyncio.run(_inspect())


@app.command("promote")
def promote_collateral_cmd(
    collateral_id: str = typer.Argument(..., help="Collateral bundle ID to promote"),
    user: str = typer.Option(
        "default", "--user", "-u", help="Requesting user identity"
    ),
    admin: bool = typer.Option(
        False,
        "--admin",
        help="Assert explicit administrative elevation (required for PERMANENT promotion)",
    ),
    format_type: str = format_option(),
    url: str | None = url_option(),
) -> None:
    """Promote a TEMPORARY collateral bundle to PERMANENT retention tier.

    Args:
        collateral_id: Target collateral bundle identifier.
        user: Requesting user identity.
        admin: Administrative elevation flag (required).
        format_type: Output presentation format.
        url: Optional remote controller base URL.
    """
    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)

    async def _promote() -> None:
        client = LocalClientAdapter(controller_url=url)
        try:
            bundle = await client.promote_collateral(
                collateral_id, user_id=user, elevate=admin
            )
            if resolved_fmt != "json":
                console.print(
                    f"[bold green]✓[/] Collateral '[bold cyan]{bundle.id}[/]' promoted to PERMANENT."
                )
            presenter.render_collateral_detail(bundle, resolved_fmt)
        except Exception as exc:
            console.print(
                f"[bold red]Error promoting collateral '{collateral_id}':[/] {exc}"
            )
            raise typer.Exit(code=1) from exc

    asyncio.run(_promote())


@app.command("pin")
def pin_collateral_cmd(
    collateral_id: str = typer.Argument(..., help="Collateral bundle ID to pin"),
    user: str = typer.Option(
        "default", "--user", "-u", help="Requesting user identity"
    ),
    admin: bool = typer.Option(
        False,
        "--admin",
        help="Assert explicit administrative elevation",
    ),
    format_type: str = format_option(),
    url: str | None = url_option(),
) -> None:
    """Pin a collateral bundle to prevent eviction during active usage.

    Args:
        collateral_id: Target collateral bundle identifier.
        user: Requesting user identity.
        admin: Administrative elevation flag.
        format_type: Output presentation format.
        url: Optional remote controller base URL.
    """
    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)

    async def _pin() -> None:
        client = LocalClientAdapter(controller_url=url)
        try:
            bundle = await client.pin_collateral(
                collateral_id, user_id=user, elevate=admin
            )
            if resolved_fmt != "json":
                console.print(
                    f"[bold green]✓[/] Pinned collateral '[bold cyan]{bundle.id}[/]' "
                    f"(active pins: {bundle.active_pin_count})."
                )
            presenter.render_collateral_detail(bundle, resolved_fmt)
        except Exception as exc:
            console.print(
                f"[bold red]Error pinning collateral '{collateral_id}':[/] {exc}"
            )
            raise typer.Exit(code=1) from exc

    asyncio.run(_pin())


@app.command("unpin")
def unpin_collateral_cmd(
    collateral_id: str = typer.Argument(..., help="Collateral bundle ID to unpin"),
    user: str = typer.Option(
        "default", "--user", "-u", help="Requesting user identity"
    ),
    admin: bool = typer.Option(
        False,
        "--admin",
        help="Assert explicit administrative elevation",
    ),
    format_type: str = format_option(),
    url: str | None = url_option(),
) -> None:
    """Unpin a collateral bundle to allow garbage collection reclamation.

    Args:
        collateral_id: Target collateral bundle identifier.
        user: Requesting user identity.
        admin: Administrative elevation flag.
        format_type: Output presentation format.
        url: Optional remote controller base URL.
    """
    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)

    async def _unpin() -> None:
        client = LocalClientAdapter(controller_url=url)
        try:
            bundle = await client.unpin_collateral(
                collateral_id, user_id=user, elevate=admin
            )
            if resolved_fmt != "json":
                console.print(
                    f"[bold green]✓[/] Unpinned collateral '[bold cyan]{bundle.id}[/]' "
                    f"(active pins: {bundle.active_pin_count})."
                )
            presenter.render_collateral_detail(bundle, resolved_fmt)
        except Exception as exc:
            console.print(
                f"[bold red]Error unpinning collateral '{collateral_id}':[/] {exc}"
            )
            raise typer.Exit(code=1) from exc

    asyncio.run(_unpin())


@app.command("delete")
def delete_collateral_cmd(
    collateral_id: str = typer.Argument(..., help="Collateral bundle ID to delete"),
    user: str = typer.Option(
        "default", "--user", "-u", help="Requesting user identity"
    ),
    admin: bool = typer.Option(
        False,
        "--admin",
        help="Assert explicit administrative elevation",
    ),
    url: str | None = url_option(),
) -> None:
    """Delete an unused collateral bundle from CAS storage.

    Args:
        collateral_id: Target collateral bundle identifier.
        user: Requesting user identity.
        admin: Administrative elevation flag.
        url: Optional remote controller base URL.
    """

    async def _delete() -> None:
        client = LocalClientAdapter(controller_url=url)
        try:
            deleted_id = await client.delete_collateral(
                collateral_id, user_id=user, elevate=admin
            )
            console.print(
                f"[bold green]✓[/] Deleted collateral bundle '[bold cyan]{deleted_id}[/]'."
            )
        except Exception as exc:
            console.print(
                f"[bold red]Error deleting collateral '{collateral_id}':[/] {exc}"
            )
            raise typer.Exit(code=1) from exc

    asyncio.run(_delete())


@app.command("evict")
def evict_collateral_cmd(
    max_age_seconds: int | None = typer.Option(
        None,
        "--max-age",
        min=1,
        help="Maximum TTL age in seconds before evicting unused temporary bundles",
    ),
    high_watermark_bytes: int | None = typer.Option(
        None,
        "--high-watermark",
        min=1,
        help="Storage high watermark ceiling in bytes to enforce during eviction",
    ),
    user: str = typer.Option(
        "default", "--user", "-u", help="Requesting user identity"
    ),
    admin: bool = typer.Option(
        False,
        "--admin",
        help="Assert explicit administrative elevation",
    ),
    format_type: str = format_option(),
    url: str | None = url_option(),
) -> None:
    """Trigger garbage collection eviction for expired temporary collateral.

    Args:
        max_age_seconds: Optional maximum age threshold in seconds.
        high_watermark_bytes: Optional storage ceiling in bytes.
        user: Requesting user identity.
        admin: Administrative elevation flag.
        format_type: Output presentation format.
        url: Optional remote controller base URL.
    """
    resolved_fmt = resolve_format(format_type)

    async def _evict() -> None:
        client = LocalClientAdapter(controller_url=url)
        try:
            evicted_ids = await client.evict_expired_collateral(
                max_age_seconds=max_age_seconds,
                high_watermark_bytes=high_watermark_bytes,
                user_id=user,
                elevate=admin,
            )
            if resolved_fmt == "json":
                console.print(
                    json.dumps(evicted_ids, indent=2), soft_wrap=True, markup=False
                )
                return
            if not evicted_ids:
                console.print("[dim]No expired temporary collateral evicted.[/]")
                return
            console.print(
                f"[bold green]✓[/] Evicted {len(evicted_ids)} bundle(s): "
                + ", ".join(evicted_ids)
            )
        except Exception as exc:
            console.print(f"[bold red]Error evicting collateral:[/] {exc}")
            raise typer.Exit(code=1) from exc

    asyncio.run(_evict())


__all__ = [
    "app",
]
