"""Unit tests validating BastionAccessPort contract.

Notes/Architectural Intent:
    Verifies that BastionAccessPort is strictly abstract and mandates required
    method contracts for zero-trust maintenance access.
"""

import inspect

import pytest

from hexaqueue_core.ports.bastion import BastionAccessPort


def test_bastion_access_port_is_abstract() -> None:
    """Verify that BastionAccessPort cannot be instantiated directly and is abstract."""
    is_abs = inspect.isabstract(BastionAccessPort)
    assert is_abs is True
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        BastionAccessPort()  # ty: ignore[call-non-callable] # type: ignore[abstract]


def test_bastion_access_port_abstract_methods() -> None:
    """Verify abstract methods on BastionAccessPort."""
    expected = {
        "audit_active_sessions",
        "generate_session_token",
        "get_connection_command",
        "terminate_session",
    }
    abstracts = BastionAccessPort.__abstractmethods__
    diff = expected.difference(abstracts)
    assert len(diff) == 0
