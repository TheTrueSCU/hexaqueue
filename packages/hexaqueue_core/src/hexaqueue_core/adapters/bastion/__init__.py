"""Pluggable zero-trust bastion and session adapters for Hexaqueue Core.

Notes/Architectural Intent:
    Exports concrete adapter implementations of BastionAccessPort for AWS SSM,
    GCP IAP, Azure Bastion, Tailscale/Teleport, and Native Break-Glass tunnels.
"""

from hexaqueue_core.adapters.bastion.aws import AWSSSMAdapter
from hexaqueue_core.adapters.bastion.azure import AzureBastionAdapter
from hexaqueue_core.adapters.bastion.base import BaseBastionAdapter
from hexaqueue_core.adapters.bastion.gcp import GCPIAPAdapter
from hexaqueue_core.adapters.bastion.native import NativeBreakGlassAdapter
from hexaqueue_core.adapters.bastion.tailscale import TailscaleTeleportAdapter

__all__ = [
    "AWSSSMAdapter",
    "AzureBastionAdapter",
    "BaseBastionAdapter",
    "GCPIAPAdapter",
    "NativeBreakGlassAdapter",
    "TailscaleTeleportAdapter",
]
