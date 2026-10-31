"""Hexaqueue: Cloud-Agnostic HPC Batch Scheduler and Distributed Job Orchestrator.

Notes/Architectural Intent:
    Root umbrella package aggregating subpackage namespaces. Discovers
    and exposes installed subpackages dynamically while providing helpful
    installation guidance on uninstalled optional extras.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hexaqueue.subpackages import (
    discover_and_register_subpackages,
    get_subpackage_dir,
    handle_missing_subpackage,
)

if TYPE_CHECKING:
    import hexaqueue_cli as cli
    import hexaqueue_collateral as collateral
    import hexaqueue_core as core
    import hexaqueue_dashboard as dashboard
    import hexaqueue_github_runner as github_runner
    import hexaqueue_gitlab_runner as gitlab_runner
    import hexaqueue_kueue as kueue
    import hexaqueue_monitor as monitor
    import hexaqueue_scanner as scanner
    import hexaqueue_server as server
    import hexaqueue_worker as worker
    import hexaqueue_workflow as workflow

__all__ = [
    "cli",
    "collateral",
    "core",
    "dashboard",
    "github_runner",
    "gitlab_runner",
    "kueue",
    "monitor",
    "scanner",
    "server",
    "worker",
    "workflow",
]

_installed_shorthands = discover_and_register_subpackages(globals(), __all__)


def __dir__() -> list[str]:
    """Return only installed package shorthands and module globals.

    Returns:
        List of exposed attribute names.
    """
    return get_subpackage_dir(globals(), _installed_shorthands)


def __getattr__(name: str) -> Any:
    """Provide clear guidance when an uninstalled optional package is accessed.

    Args:
        name: Name of requested attribute.

    Returns:
        Subpackage reference if dynamically loaded.

    Raises:
        AttributeError: If subpackage is not installed or unknown.
    """
    return handle_missing_subpackage(name, __all__)
