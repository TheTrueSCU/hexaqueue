"""Unit tests for RbacPolicyPort abstract interface."""

from __future__ import annotations

from typing import Any, cast

import pytest

from hexaqueue_dashboard.ports.rbac import RbacPolicyPort


def test_rbac_policy_port_is_abstract() -> None:
    """Verify RbacPolicyPort cannot be instantiated directly."""
    port_cls = cast("Any", RbacPolicyPort)
    with pytest.raises(TypeError):
        port_cls()
