"""Tests for LeaderElectionPort interface."""

import inspect

from hexaqueue_core.ports.coordination import LeaderElectionPort


def test_leader_election_port_is_abstract() -> None:
    """Verify LeaderElectionPort is an abstract interface."""
    assert inspect.isabstract(LeaderElectionPort)
    assert "acquire_leadership" in LeaderElectionPort.__abstractmethods__
