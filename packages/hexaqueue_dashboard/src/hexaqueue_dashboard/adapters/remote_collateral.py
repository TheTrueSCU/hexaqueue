"""Re-export of shared HTTP remote collateral adapter for Hexaqueue Dashboard.

Notes/Architectural Intent:
    Preserves existing ``hexaqueue_dashboard.adapters.remote_collateral`` import
    paths while delegating the single authoritative implementation to
    ``hexaqueue_server.adapters.http.collateral``.
"""

from hexaqueue_server.adapters.http.collateral import HttpCollateralServiceAdapter

__all__ = [
    "HttpCollateralServiceAdapter",
]
