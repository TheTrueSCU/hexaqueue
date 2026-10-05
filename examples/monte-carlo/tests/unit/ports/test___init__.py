"""Test ports exports."""

from monte_carlo.ports.simulator import SimulationEnginePort


def test_ports_exports() -> None:
    """Verify ports interfaces are available."""
    assert SimulationEnginePort is not None
