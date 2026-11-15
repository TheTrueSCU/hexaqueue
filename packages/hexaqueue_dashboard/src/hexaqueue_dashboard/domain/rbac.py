"""Domain models and pure evaluation logic for Hexaqueue Dashboard RBAC.

Notes/Architectural Intent:
    Defines storage-agnostic RBAC principal models and pure permission evaluation
    rules so authorization policies can be persisted in Oracle ADB, local SQLite,
    or in-memory stores without coupling domain logic to any database engine.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RbacPrincipal(BaseModel):
    """Represents an authenticated dashboard or CI principal and its RBAC grants.

    Notes/Architectural Intent:
        Decouples principal identity and role/permission grants from hardcoded
        usernames, enabling dynamic management in Oracle ADB or local SQLite.
        Defaults to least-privilege `guest` role when no roles are specified.
    """

    principal_id: str = Field(..., min_length=1, description="Unique principal name")
    hashed_secret: str = Field(
        ..., min_length=1, description="PBKDF2 password or API token hash"
    )
    roles: frozenset[str] = Field(
        default_factory=lambda: frozenset({"guest"}),
        description="Assigned RBAC roles (default least-privilege guest)",
    )
    permissions: frozenset[str] = Field(
        default_factory=frozenset,
        description="Fine-grained permission grants (e.g. jobs:cancel:any)",
    )
    is_active: bool = Field(default=True, description="Whether principal is enabled")


def evaluate_rbac_permission(
    principal: RbacPrincipal,
    action: str,
    resource_owner: str | None = None,
) -> bool:
    """Evaluate whether a principal may perform an action on a resource.

    Args:
        principal: Authenticated RbacPrincipal.
        action: Logical action string (e.g. 'jobs:cancel').
        resource_owner: Optional owner principal_id of the target resource.

    Returns:
        True if permitted, False otherwise.
    """
    if not principal.is_active:
        return False
    if "admin" in principal.roles or "*" in principal.permissions:
        return True
    if f"{action}:any" in principal.permissions:
        return True
    if action in principal.permissions:
        return True
    return bool(
        resource_owner is not None
        and resource_owner == principal.principal_id
        and ("ci" in principal.roles or "user" in principal.roles)
    )


__all__ = [
    "evaluate_rbac_permission",
    "RbacPrincipal",
]
