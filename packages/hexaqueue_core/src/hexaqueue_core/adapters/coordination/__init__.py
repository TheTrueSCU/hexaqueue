"""Coordination adapters for distributed locking and leader election."""

from hexaqueue_core.adapters.coordination.in_memory import (
    InMemoryLeaderElectionAdapter,
)

__all__ = [
    "InMemoryLeaderElectionAdapter",
]
