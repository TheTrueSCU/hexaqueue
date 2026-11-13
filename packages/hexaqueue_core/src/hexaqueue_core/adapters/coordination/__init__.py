"""Coordination adapters for distributed locking and leader election."""

from hexaqueue_core.adapters.coordination.in_memory import (
    InMemoryLeaderAdapter,
    InMemoryLeaderElectionAdapter,
)
from hexaqueue_core.adapters.coordination.kubernetes import (
    KubernetesLeaseClientProtocol,
    KubernetesLeaseLeaderAdapter,
)

__all__ = [
    "InMemoryLeaderAdapter",
    "InMemoryLeaderElectionAdapter",
    "KubernetesLeaseClientProtocol",
    "KubernetesLeaseLeaderAdapter",
]
