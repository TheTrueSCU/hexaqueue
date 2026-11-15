"""Unit tests for hexaqueue_dashboard.ports exports."""

from hexaqueue_dashboard import ports


def test_ports_exports() -> None:
    """Verify RbacPolicyPort is exported in ports.__all__."""
    exports = ports.__all__
    assert exports == ["RbacPolicyPort"]
