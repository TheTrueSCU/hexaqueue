"""FastAPI REST presentation adapters for Hexaqueue Server.

Notes/Architectural Intent:
    Exposes OpenAPI routes for all Hexaqueue capabilities with 100% surface parity
    to CLI and Web Dashboard. Implements the Principle of Least Privilege:
    callers act under their natural identity by default, with administrative
    elevation asserted explicitly via header (`X-Hexaqueue-Elevate: true`) or
    query parameter (`?elevate=true`).
"""

from hexaqueue_server.adapters.api.app import (
    create_server_api_router,
    create_server_app,
)
from hexaqueue_server.adapters.api.auth import get_auth_context

__all__ = [
    "create_server_api_router",
    "create_server_app",
    "get_auth_context",
]
