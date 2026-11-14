"""Unit tests for hexaqueue_core.ports.ha re-export module."""

import inspect

from hexaqueue_core.ports.coordination import LeaderElectionPort as CoreLeaderPort
from hexaqueue_core.ports.ha import LeaderElectionPort, LeaderLifecycleCallback


def test_ha_port_reexports_leader_election_port() -> None:
    """Verify hexaqueue_core.ports.ha re-exports LeaderElectionPort and callback type."""
    is_abstract = inspect.isabstract(LeaderElectionPort)
    assert is_abstract is True
    assert LeaderElectionPort is CoreLeaderPort
    assert LeaderLifecycleCallback is not None
