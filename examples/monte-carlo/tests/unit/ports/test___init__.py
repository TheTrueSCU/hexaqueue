"""Test ports exports."""

import monte_carlo.ports


def test_ports_exports() -> None:
    """Verify ports __all__."""
    assert hasattr(monte_carlo.ports, "SimulationEnginePort")
