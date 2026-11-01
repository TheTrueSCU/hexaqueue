"""Unit tests for create_cloud_governors factory."""

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.credentials import FederatedCspCredentialsConfig
from hexaqueue_core.ports.pool import InstancePoolGovernorPort
from hexaqueue_server.adapters.cloud.aws import AwsAutoScalingGroupAdapter
from hexaqueue_server.adapters.cloud.azure import AzureScaleSetAdapter
from hexaqueue_server.adapters.cloud.factory import create_cloud_governors
from hexaqueue_server.adapters.cloud.gcp import GcpManagedInstanceGroupAdapter
from hexaqueue_server.adapters.cloud.oci import OciInstancePoolAdapter


def test_create_cloud_governors_default() -> None:
    """Verify create_cloud_governors instantiates all four cloud governors."""
    governors = create_cloud_governors(FederatedCspCredentialsConfig())

    has_oci = CspProvider.OCI in governors
    assert has_oci is True
    has_aws = CspProvider.AWS in governors
    assert has_aws is True
    has_gcp = CspProvider.GCP in governors
    assert has_gcp is True
    has_azure = CspProvider.AZURE in governors
    assert has_azure is True

    # Type verification
    assert isinstance(governors[CspProvider.OCI], OciInstancePoolAdapter)
    assert isinstance(governors[CspProvider.AWS], AwsAutoScalingGroupAdapter)
    assert isinstance(governors[CspProvider.GCP], GcpManagedInstanceGroupAdapter)
    assert isinstance(governors[CspProvider.AZURE], AzureScaleSetAdapter)

    # All implement the port
    for gov in governors.values():
        is_port = isinstance(gov, InstancePoolGovernorPort)
        assert is_port is True


def test_create_cloud_governors_from_env() -> None:
    """Verify create_cloud_governors resolves from environment when credentials omitted."""
    governors = create_cloud_governors()
    count = len(governors)
    assert count == 4
