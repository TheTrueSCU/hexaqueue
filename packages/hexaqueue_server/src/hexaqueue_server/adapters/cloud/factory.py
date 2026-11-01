"""Factory for creating CSP instance pool governors from federated credentials.

Notes/Architectural Intent:
    Instantiates and configures InstancePoolGovernorPort adapters for OCI, AWS,
    GCP, and Azure dynamically based on configured FederatedCspCredentialsConfig.
    Guarantees that unconfigured providers default safely to hermetic mock/local pools
    without failing startup or requiring cloud credentials during local development.
"""

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.credentials import FederatedCspCredentialsConfig
from hexaqueue_core.ports.pool import InstancePoolGovernorPort
from hexaqueue_server.adapters.cloud.aws import AwsAutoScalingGroupAdapter
from hexaqueue_server.adapters.cloud.azure import AzureScaleSetAdapter
from hexaqueue_server.adapters.cloud.gcp import GcpManagedInstanceGroupAdapter
from hexaqueue_server.adapters.cloud.oci import OciInstancePoolAdapter


def create_cloud_governors(
    credentials: FederatedCspCredentialsConfig | None = None,
) -> dict[CspProvider, InstancePoolGovernorPort]:
    """Create a mapping of CSP providers to configured instance pool governor adapters.

    Args:
        credentials: Optional FederatedCspCredentialsConfig. When omitted, resolves
            credentials automatically from environment variables and .env files.

    Returns:
        Dictionary mapping CspProvider enum members to active InstancePoolGovernorPort instances.

    Notes/Architectural Intent:
        Enables multi-cloud orchestration by dynamically providing governors for
        OCI, AWS, GCP, and Azure. Each adapter attempts live cloud connection if
        credentials are provided, falling back seamlessly to local mock stores.
    """
    creds = credentials or FederatedCspCredentialsConfig.from_env()

    return {
        CspProvider.OCI: OciInstancePoolAdapter.from_credentials(creds.oci),
        CspProvider.AWS: AwsAutoScalingGroupAdapter.from_credentials(creds.aws),
        CspProvider.GCP: GcpManagedInstanceGroupAdapter.from_credentials(creds.gcp),
        CspProvider.AZURE: AzureScaleSetAdapter.from_credentials(creds.azure),
    }


__all__ = [
    "create_cloud_governors",
]
