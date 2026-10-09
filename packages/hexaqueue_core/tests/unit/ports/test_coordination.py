"""Tests for LeaderElectionPort interface."""

import pytest

from hexaqueue_core.ports.coordination import LeaderElectionPort


def test_leader_election_port_is_abstract() -> None:
    """Verify LeaderElectionPort cannot be instantiated directly."""
    with pytest.raises(TypeError):
        LeaderElectionPort()  # type: ignore[abstract]
