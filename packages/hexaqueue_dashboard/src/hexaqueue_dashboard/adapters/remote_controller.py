"""Re-export of shared HTTP remote controller adapter for Hexaqueue Dashboard.

Notes/Architectural Intent:
    Preserves existing ``hexaqueue_dashboard.adapters.remote_controller`` import
    paths while delegating the single authoritative implementation to
    ``hexaqueue_server.adapters.http.controller``.
"""

from hexaqueue_server.adapters.http.controller import HttpSchedulerControllerAdapter

__all__ = [
    "HttpSchedulerControllerAdapter",
]
