"""Bootstrapper port interface re-exported from Hexastack Core.

Notes/Architectural Intent:
    Re-exports BootstrapperPort so that all Hexaqueue packages adhere to the
    standardized 2-phase lifecycle contract.
"""

from hexastack_core.ports.bootstrap import BootstrapperPort

__all__ = [
    "BootstrapperPort",
]
