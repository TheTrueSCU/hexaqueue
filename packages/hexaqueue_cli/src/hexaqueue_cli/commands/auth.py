"""Authentication and credential management CLI commands.

Notes/Architectural Intent:
    Prompts interactively with hidden input for both current and confirmed new
    passwords, wrapping credentials in SecretStr so plaintext values never
    appear in CLI flags or logs.
"""

from __future__ import annotations

from typing import Annotated

import typer
from pydantic import SecretStr
from rich.console import Console

from hexaqueue_cli.adapters.auth_rotation import rotate_dashboard_password

app = typer.Typer(
    name="auth",
    help="Dashboard authentication and credential management",
    no_args_is_help=True,
)
console = Console()


@app.command("rotate-password")
def rotate_password(
    username: Annotated[
        str,
        typer.Option("--user", "-u", help="Principal username to rotate"),
    ] = "rjdw",
    dashboard_url: Annotated[
        str | None,
        typer.Option(
            "--url", help="Dashboard base URL (defaults to HEXAQUEUE_DASHBOARD_URL)"
        ),
    ] = None,
    offline: Annotated[
        bool,
        typer.Option(
            "--offline", help="Bypass HTTP and update Oracle ADB / SQLite directly"
        ),
    ] = False,
) -> None:
    """Verify existing password and rotate to a confirmed new password.

    Args:
        username: Target RBAC principal username.
        dashboard_url: Optional dashboard HTTP endpoint override.
        offline: Skip HTTP and write directly to configured ADB/SQLite store.
    """
    current_secret = SecretStr(typer.prompt("Current password", hide_input=True))
    new_secret = SecretStr(
        typer.prompt("New password", hide_input=True, confirmation_prompt=True)
    )
    try:
        result = rotate_dashboard_password(
            username=username,
            current_secret=current_secret,
            new_secret=new_secret,
            dashboard_url=dashboard_url,
            offline=offline,
        )
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]{result}[/green]")


__all__ = [
    "app",
    "rotate_password",
]
