"""Test ports package exports."""

import monopoly.ports


def test_ports_exports() -> None:
    """Verify ports package __all__."""
    has_port = hasattr(monopoly.ports, "ClusterSimulatorPort")
    assert has_port is True
