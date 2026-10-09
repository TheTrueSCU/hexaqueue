"""Authentication and elevation resolution dependencies for Hexaqueue REST API.

Notes/Architectural Intent:
    Implements the Principle of Least Privilege: callers act under their natural
    identity by default, with administrative elevation asserted explicitly via
    header (`X-Hexaqueue-Elevate: true`) or query parameter (`?elevate=true` / `?admin=true`).
"""

import os
from typing import Annotated

from fastapi import Header, HTTPException, Query, status


def get_auth_context(
    x_hexaqueue_user: Annotated[str | None, Header()] = None,
    user: Annotated[str | None, Query()] = None,
    x_hexaqueue_elevate: Annotated[bool, Header()] = False,
    elevate: Annotated[bool, Query()] = False,
    admin: Annotated[bool, Query()] = False,
    x_hexaqueue_admin_token: Annotated[str | None, Header()] = None,
    admin_token: Annotated[str | None, Query()] = None,
) -> tuple[str, bool]:
    """Resolve requesting user identity and elevation status.

    Args:
        x_hexaqueue_user: User identity from X-Hexaqueue-User header.
        user: User identity from user query parameter.
        x_hexaqueue_elevate: Elevation flag from X-Hexaqueue-Elevate header.
        elevate: Elevation flag from elevate query parameter.
        admin: Administrative elevation flag from admin query parameter.
        x_hexaqueue_admin_token: Administrative bearer token from header.
        admin_token: Administrative token from query parameter.

    Returns:
        Tuple of (resolved_user_id, is_elevated).

    Raises:
        HTTPException: If admin elevation is asserted but HEXAQUEUE_ADMIN_TOKEN is configured and invalid.

    Notes/Architectural Intent:
        Centralized authentication and elevation resolution dependency for REST endpoints.
    """
    user_id = x_hexaqueue_user or user or "default"
    requested_elevation = bool(x_hexaqueue_elevate or elevate or admin)
    if requested_elevation:
        configured_token = os.environ.get("HEXAQUEUE_ADMIN_TOKEN")
        if configured_token is not None:
            provided_token = x_hexaqueue_admin_token or admin_token
            if provided_token != configured_token:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid or missing administrative elevation token.",
                )
            is_elevated = True
        elif os.environ.get("HEXAQUEUE_ALLOW_ANONYMOUS_ADMIN", "0") != "1":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrative elevation requires HEXAQUEUE_ADMIN_TOKEN to be configured.",
            )
        else:
            is_elevated = True
    else:
        is_elevated = False
    return user_id, is_elevated


__all__ = [
    "get_auth_context",
]
