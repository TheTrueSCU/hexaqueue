"""HTTP remote control-plane and collateral adapters for distributed Hexaqueue clients.

Notes/Architectural Intent:
    Exposes ``HttpSchedulerControllerAdapter`` and ``HttpCollateralServiceAdapter``
    for process-isolated clients such as ``hexaqueue-dashboard`` and ``hexaqueue-cli``
    connecting to a remote ``hexaqueue-server`` REST API (``/v1/*``).
"""

from hexaqueue_server.adapters.http.collateral import HttpCollateralServiceAdapter
from hexaqueue_server.adapters.http.controller import HttpSchedulerControllerAdapter

__all__ = [
    "HttpCollateralServiceAdapter",
    "HttpSchedulerControllerAdapter",
]
