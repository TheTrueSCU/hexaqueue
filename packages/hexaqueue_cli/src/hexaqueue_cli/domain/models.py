"""Domain models for CLI cluster monitoring and statistics.

Notes/Architectural Intent:
    Defines presentation and reporting payloads for `hq stat`, `hq top`, and `hq nodes`.
"""

from hexaqueue_core.domain.cqrs import ClusterStatsReport

__all__ = [
    "ClusterStatsReport",
]
