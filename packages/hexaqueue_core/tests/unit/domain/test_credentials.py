"""Unit tests for Cloud Service Provider (CSP) credentials configuration and SecretStr protection."""

from pydantic import SecretStr

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.credentials import (
    AwsCredentialsConfig,
    AzureCredentialsConfig,
    FederatedCspCredentialsConfig,
    GcpCredentialsConfig,
    OciCredentialsConfig,
)


def test_oci_credentials_config_and_secret_masking() -> None:
    """Test OCI credential creation, SecretStr masking, and configuration detection."""
    cfg = OciCredentialsConfig(
        tenancy_ocid="ocid1.tenancy.oc1..aaaa1111",
        user_ocid="ocid1.user.oc1..bbbb2222",
        fingerprint="12:34:56:78:90:ab",
        key_content=SecretStr("SUPER_SECRET_OCI_PEM_KEY_CONTENT"),
    )
    assert cfg.is_configured is True
    assert cfg.key_content is not None
    assert cfg.key_content.get_secret_value() == "SUPER_SECRET_OCI_PEM_KEY_CONTENT"

    # Invariant: SecretStr is never leaked in repr, str, or dict
    repr_str = repr(cfg)
    assert "SUPER_SECRET_OCI_PEM_KEY_CONTENT" not in repr_str
    assert "**********" in repr_str

    # Test ambient instance principals
    ambient_cfg = OciCredentialsConfig(use_instance_principals=True)
    assert ambient_cfg.is_configured is True

    # Test unconfigured
    unconf = OciCredentialsConfig()
    assert unconf.is_configured is False


def test_aws_credentials_config_and_secret_masking() -> None:
    """Test AWS credential creation, SecretStr masking, and IAM role detection."""
    cfg = AwsCredentialsConfig(
        access_key_id=SecretStr("AKIAIOSFODNN7EXAMPLE"),
        secret_access_key=SecretStr("wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"),
        session_token=SecretStr("TOKEN123"),
        region="us-west-2",
    )
    assert cfg.is_configured is True
    assert cfg.access_key_id is not None
    assert cfg.secret_access_key is not None

    # Invariant: Credentials masked in repr
    dump_str = repr(cfg)
    assert "wJalrXUtnFEMI/K7MDENG" not in dump_str
    assert "AKIAIOSFODNN7EXAMPLE" not in dump_str

    # Test IAM Role ambient authentication
    iam_cfg = AwsCredentialsConfig(use_iam_role=True)
    assert iam_cfg.is_configured is True

    # Test named profile
    prof_cfg = AwsCredentialsConfig(profile="hexaqueue-prod")
    assert prof_cfg.is_configured is True

    # Test unconfigured
    unconf = AwsCredentialsConfig()
    assert unconf.is_configured is False


def test_gcp_credentials_config_and_secret_masking() -> None:
    """Test GCP credential creation, SecretStr masking, and Workload Identity detection."""
    cfg = GcpCredentialsConfig(
        project_id="my-gcp-project",
        service_account_json=SecretStr(
            '{"type": "service_account", "private_key": "SECRET"}'
        ),
    )
    assert cfg.is_configured is True
    assert cfg.service_account_json is not None
    assert cfg.service_account_json.get_secret_value().startswith(
        '{"type": "service_account"'
    )

    # Invariant: JSON payload masked
    assert "private_key" not in repr(cfg)

    # Test ambient Workload Identity
    wi_cfg = GcpCredentialsConfig(use_workload_identity=True)
    assert wi_cfg.is_configured is True

    # Test key file path
    file_cfg = GcpCredentialsConfig(service_account_file="/etc/secrets/gcp.json")
    assert file_cfg.is_configured is True

    # Test unconfigured
    unconf = GcpCredentialsConfig()
    assert unconf.is_configured is False


def test_azure_credentials_config_and_secret_masking() -> None:
    """Test Azure credential creation, SecretStr masking, and Managed Identity detection."""
    cfg = AzureCredentialsConfig(
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret=SecretStr("SUPER_SECRET_CLIENT_SECRET"),
    )
    assert cfg.is_configured is True
    assert cfg.client_secret is not None
    assert cfg.client_secret.get_secret_value() == "SUPER_SECRET_CLIENT_SECRET"

    # Invariant: Client secret masked
    assert "SUPER_SECRET_CLIENT_SECRET" not in repr(cfg)

    # Test ambient Managed Identity
    mi_cfg = AzureCredentialsConfig(use_managed_identity=True)
    assert mi_cfg.is_configured is True

    # Test unconfigured
    unconf = AzureCredentialsConfig()
    assert unconf.is_configured is False


def test_federated_csp_credentials_from_env() -> None:
    """Test resolving multi-cloud credentials securely from environment mapping."""
    fake_env = {
        # OCI
        "HEXAQUEUE_OCI_TENANCY_OCID": "ocid1.tenancy.oc1..test",
        "HEXAQUEUE_OCI_USER_OCID": "ocid1.user.oc1..test",
        "HEXAQUEUE_OCI_FINGERPRINT": "aa:bb:cc:dd",
        "HEXAQUEUE_OCI_KEY_FILE": "/etc/keys/oci.pem",
        "HEXAQUEUE_OCI_REGION": "us-ashburn-1",
        # AWS (standard SDK fallback)
        "AWS_ACCESS_KEY_ID": "AKIA_TEST_ID",
        "AWS_SECRET_ACCESS_KEY": "AWS_SECRET_TEST",
        "AWS_DEFAULT_REGION": "us-east-1",
        # GCP (standard SDK fallback)
        "GOOGLE_APPLICATION_CREDENTIALS": "/etc/keys/gcp.json",
        "GCP_PROJECT": "test-project",
        # Azure
        "HEXAQUEUE_AZURE_TENANT_ID": "azure-tenant-1",
        "HEXAQUEUE_AZURE_CLIENT_ID": "azure-client-1",
        "HEXAQUEUE_AZURE_CLIENT_SECRET": "azure-secret-1",
    }

    fed = FederatedCspCredentialsConfig.from_env(fake_env)

    # Provider verification
    assert fed.is_provider_configured(CspProvider.OCI) is True
    assert fed.is_provider_configured(CspProvider.AWS) is True
    assert fed.is_provider_configured(CspProvider.GCP) is True
    assert fed.is_provider_configured(CspProvider.AZURE) is True
    assert fed.is_provider_configured(CspProvider.LOCAL) is True
    assert fed.is_provider_configured(CspProvider.ONPREM) is True


def test_empty_env_resolution() -> None:
    """Test environment resolution with empty environment."""
    fed = FederatedCspCredentialsConfig.from_env({})
    assert fed.is_provider_configured(CspProvider.OCI) is False
    assert fed.is_provider_configured(CspProvider.AWS) is False
    assert fed.is_provider_configured(CspProvider.GCP) is False
    assert fed.is_provider_configured(CspProvider.AZURE) is False
    assert fed.is_provider_configured(CspProvider.LOCAL) is True
