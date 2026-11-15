"""Unit tests for RbacPolicyPort abstract interface."""

from __future__ import annotations

import inspect

import pytest

from hexaqueue_dashboard.ports.rbac import RbacPolicyPort


def test_rbac_policy_port_is_abstract() -> None:
    """Verify RbacPolicyPort cannot be instantiated directly."""
    is_abs = inspect.isabstract(RbacPolicyPort)
    assert is_abs is True
    with pytest.raises(TypeError):
        type(RbacPolicyPort).__call__(RbacPolicyPort)
