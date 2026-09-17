"""CLI option factories and formatting resolvers for Hexaqueue CLI applications.

Notes/Architectural Intent:
    Provides standardized Typer option factories and stdout pipe-detection routines.
    When format is 'auto', automatically routes to structured JSON when piped into
    downstream Unix utilities (jq, grep) or styled Rich/table output when attached to an
    interactive TTY. Aligns with the Hexa ecosystem CLI standards.
"""

from __future__ import annotations

import sys
from enum import Enum
from typing import Any

import typer

from hexaqueue_cli.domain.options import OutputFormat

__all__ = [
    "format_option",
    "resolve_format",
]


def resolve_format(
    format_type: str | OutputFormat,
    default_tty: str = "table",
    default_pipe: str = "json",
) -> str:
    """Resolve an output format string, handling auto-detection for pipes.

    Args:
        format_type: The format chosen by user or default ('auto', 'table', 'json', etc.).
        default_tty: Default format when connected to an interactive terminal.
        default_pipe: Default format when stdout is piped or redirected.

    Returns:
        Normalized lowercase format string (e.g. 'table', 'json', 'rich').

    Notes/Architectural Intent:
        When format_type is 'auto', inspects sys.stdout.isatty() to choose between
        structured machine-readable format for pipelines or visual format for humans.
    """
    raw = (
        format_type.value
        if isinstance(format_type, Enum)
        else str(format_type).lower().strip()
    )
    if raw == OutputFormat.AUTO.value:
        if not sys.stdout.isatty():
            return default_pipe
        return default_tty
    return raw


def format_option(
    default: str = "table",
    help_text: str = "Output presentation format (table, json, markdown, rich, plain, auto).",
) -> Any:
    """Construct a standardized Typer option for format selection.

    Args:
        default: Default format option value.
        help_text: Help string to render in CLI usage catalogs.

    Returns:
        Configured Typer Option specification.

    Notes/Architectural Intent:
        Standardizes '-f' / '--format' flag across all Hexaqueue CLI commands.
    """
    return typer.Option(default, "-f", "--format", help=help_text)
