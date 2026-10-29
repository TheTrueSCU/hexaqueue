"""Cloud Service Provider (CSP) instance pool adapters.

Notes/Architectural Intent:
    Encapsulates cloud-specific drivers and SDK integrations for AWS Auto Scaling
    Groups (ASGs), GCP Managed Instance Groups (MIGs), and Azure Virtual Machine
    Scale Sets (VMSS) behind the InstancePoolGovernorPort interface.
"""

from hexaqueue_server.adapters.cloud.aws import AwsAutoScalingGroupAdapter
from hexaqueue_server.adapters.cloud.azure import AzureScaleSetAdapter
from hexaqueue_server.adapters.cloud.gcp import GcpManagedInstanceGroupAdapter

__all__ = [
    "AwsAutoScalingGroupAdapter",
    "AzureScaleSetAdapter",
    "GcpManagedInstanceGroupAdapter",
]
