"""Domain representations for CLI output presentation formats.

Notes/Architectural Intent:
    Defines the canonical output format enumeration shared across CLI presenters,
    command runners, and reporting bridges. Fulfills the cross-ecosystem CLI alignment invariant.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "OutputFormat",
]


class OutputFormat(StrEnum):
    """Supported output presentation formats for CLI commands."""

    AUTO = "auto"
    JSON = "json"
    MARKDOWN = "markdown"
    PLAIN = "plain"
    RICH = "rich"
    TABLE = "table"
