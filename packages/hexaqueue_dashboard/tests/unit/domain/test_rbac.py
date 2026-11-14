"""Unit tests for Hexaqueue Dashboard RBAC domain model and permission rules."""

from __future__ import annotations

from hexaqueue_dashboard.domain.rbac import RbacPrincipal, evaluate_rbac_permission


def test_rbac_principal_defaults_to_guest_least_privilege() -> None:
    """Verify RbacPrincipal defaults to guest role with no mutation rights."""
    guest = RbacPrincipal(principal_id="viewer-1", hashed_secret="hash-1")
    roles = guest.roles
    assert roles == frozenset({"guest"})

    can_kill_other = evaluate_rbac_permission(
        guest, "jobs:cancel", resource_owner="rjdw"
    )
    assert can_kill_other is False

    can_kill_self = evaluate_rbac_permission(
        guest, "jobs:cancel", resource_owner="viewer-1"
    )
    assert can_kill_self is False


def test_rbac_admin_and_ci_ownership_evaluation() -> None:
    """Verify admin can act on any resource while ci is scoped to its own."""
    admin = RbacPrincipal(
        principal_id="rjdw",
        hashed_secret="hash-a",
        roles=frozenset({"admin"}),
    )
    ci = RbacPrincipal(
        principal_id="hexaqueue-ci",
        hashed_secret="hash-c",
        roles=frozenset({"ci"}),
    )

    admin_on_ci = evaluate_rbac_permission(
        admin, "jobs:cancel", resource_owner="hexaqueue-ci"
    )
    assert admin_on_ci is True

    ci_on_rjdw = evaluate_rbac_permission(ci, "jobs:cancel", resource_owner="rjdw")
    assert ci_on_rjdw is False

    ci_on_own = evaluate_rbac_permission(
        ci, "jobs:cancel", resource_owner="hexaqueue-ci"
    )
    assert ci_on_own is True
