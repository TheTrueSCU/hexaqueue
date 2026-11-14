"""High-availability leader election port re-exports (`hexaqueue_core.ports.ha`).

Notes/Architectural Intent:
    Exposes LeaderElectionPort and LeaderLifecycleCallback under the canonical
    `hexaqueue_core.ports.ha` module namespace while preserving full backward
    compatibility with `hexaqueue_core.ports.coordination`.
"""

from hexaqueue_core.ports.coordination import (
    LeaderElectionPort,
    LeaderLifecycleCallback,
)

__all__ = [
    "LeaderElectionPort",
    "LeaderLifecycleCallback",
]
