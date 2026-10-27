"""Hexaqueue utility modules and helpers.

Notes/Architectural Intent:
    Houses cross-cutting helpers (such as dynamic dependency imports)
    isolated from domain models and architectural ports.
"""

from __future__ import annotations

from hexaqueue_core.utils.imports import optional_dependency, require_dependency

__all__ = [
    "optional_dependency",
    "require_dependency",
]
