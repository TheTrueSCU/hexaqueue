"""Cloud Service Provider (CSP) credential models and environment configuration.

Notes/Architectural Intent:
    Guarantees strict credential isolation by wrapping API keys, tokens, and
    service account payloads in pydantic SecretStr to prevent leakage in logs,
    traces, or exceptions. Supports ambient cloud authentication (Instance
    Principals, Workload Identity, IAM Roles) alongside unversioned environment
    variable resolution (HEXAQUEUE_CSP_*).
"""

import contextlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.utils.imports import optional_dependency


def _parse_bool(val: str | None) -> bool:
    """Parse string representation of boolean."""
    return str(val).strip().lower() in ("true", "1", "yes", "on") if val else False


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse key=value environment variables from an unversioned .env file.

    Notes/Architectural Intent:
        Uses `python-dotenv` via `optional_dependency('dotenv')` when available
        for multiline and bash variable expansions, falling back to a pure
        zero-dependency standard library parser.
    """
    if not path.is_file():
        return {}

    dotenv_mod = optional_dependency("dotenv")
    if dotenv_mod is not None:
        with contextlib.suppress(Exception):
            values = dotenv_mod.dotenv_values(path)
            return {str(k): str(v) for k, v in values.items() if v is not None}

    res: dict[str, str] = {}
    with contextlib.suppress(OSError, UnicodeDecodeError):
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("export "):
                stripped = stripped[7:].strip()
            if "=" in stripped:
                k, v = stripped.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k:
                    res[k] = v
    return res


def _discover_and_merge_env(cwd: Path | None = None) -> dict[str, str]:
    """Discover .env and .env.local files walking up directory tree, merging under os.environ."""
    root = (cwd or Path.cwd()).resolve()
    merged: dict[str, str] = {}
    candidates: list[Path] = [root, *root.parents]
    for directory in reversed(candidates):
        env_file = directory / ".env"
        env_local = directory / ".env.local"
        if env_file.is_file():
            merged.update(_parse_env_file(env_file))
        if env_local.is_file():
            merged.update(_parse_env_file(env_local))
    merged.update(os.environ)
    return merged


class OciCredentialsConfig(BaseModel):
    """Oracle Cloud Infrastructure (OCI) credential configuration.

    Args:
        tenancy_ocid: OCI Tenancy OCID.
        user_ocid: OCI User OCID.
        fingerprint: OCI API key fingerprint.
        key_file: Path to local unversioned PEM private key.
        key_content: Inline PEM private key content wrapped in SecretStr.
        region: OCI target region identifier.
        use_instance_principals: Whether to authenticate via OCI Instance Principals.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fingerprint: str | None = Field(default=None, description="API key fingerprint")
    key_content: SecretStr | None = Field(
        default=None, description="Inline PEM private key"
    )
    key_file: str | None = Field(
        default=None, description="Path to PEM private key file"
    )
    region: str = Field(default="us-ashburn-1", description="OCI Region")
    tenancy_ocid: str | None = Field(default=None, description="Tenancy OCID")
    use_instance_principals: bool = Field(
        default=False, description="Use ambient OCI Instance Principals"
    )
    user_ocid: str | None = Field(default=None, description="User OCID")

    @property
    def is_configured(self) -> bool:
        """Check if OCI credentials or ambient authentication are configured."""
        if self.use_instance_principals:
            return True
        has_keys = bool(self.key_file or self.key_content)
        return bool(
            self.tenancy_ocid and self.user_ocid and self.fingerprint and has_keys
        )


class AwsCredentialsConfig(BaseModel):
    """Amazon Web Services (AWS) credential configuration.

    Args:
        access_key_id: AWS Access Key ID.
        secret_access_key: AWS Secret Access Key.
        session_token: Optional temporary session token.
        region: AWS Default Region.
        profile: AWS Named Profile.
        use_iam_role: Whether to authenticate via ambient EC2/ECS IAM Role.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    access_key_id: SecretStr | None = Field(
        default=None, description="AWS Access Key ID"
    )
    profile: str | None = Field(default=None, description="AWS named profile")
    region: str = Field(default="us-east-1", description="AWS Region")
    secret_access_key: SecretStr | None = Field(
        default=None, description="AWS Secret Access Key"
    )
    session_token: SecretStr | None = Field(
        default=None, description="AWS STS Session Token"
    )
    use_iam_role: bool = Field(
        default=False, description="Use ambient EC2/ECS/EKS IAM Role"
    )

    @property
    def is_configured(self) -> bool:
        """Check if AWS credentials or ambient authentication are configured."""
        if self.use_iam_role or self.profile:
            return True
        return bool(self.access_key_id and self.secret_access_key)


class GcpCredentialsConfig(BaseModel):
    """Google Cloud Platform (GCP) credential configuration.

    Args:
        project_id: GCP project identifier.
        service_account_file: Path to service account JSON key file.
        service_account_json: Inline service account JSON payload.
        zone: GCP target compute zone.
        use_workload_identity: Whether to authenticate via ambient Workload Identity.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str | None = Field(default=None, description="GCP Project ID")
    service_account_file: str | None = Field(
        default=None, description="Service account JSON key path"
    )
    service_account_json: SecretStr | None = Field(
        default=None, description="Inline service account JSON"
    )
    use_workload_identity: bool = Field(
        default=False, description="Use ambient GCP Workload Identity / ADC"
    )
    zone: str = Field(default="us-central1-a", description="GCP Zone")

    @property
    def is_configured(self) -> bool:
        """Check if GCP credentials or ambient authentication are configured."""
        if self.use_workload_identity:
            return True
        return bool(self.service_account_file or self.service_account_json)


class AzureCredentialsConfig(BaseModel):
    """Microsoft Azure credential configuration.

    Args:
        tenant_id: Azure Active Directory Tenant ID.
        client_id: Azure Service Principal Client / App ID.
        client_secret: Azure Service Principal Secret.
        subscription_id: Azure Subscription ID.
        location: Azure default location.
        use_managed_identity: Whether to authenticate via ambient Managed Identity.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_id: str | None = Field(
        default=None, description="Service Principal Client ID"
    )
    client_secret: SecretStr | None = Field(
        default=None, description="Service Principal Secret"
    )
    location: str = Field(default="eastus", description="Azure Location")
    subscription_id: str | None = Field(
        default=None, description="Azure Subscription ID"
    )
    tenant_id: str | None = Field(default=None, description="Azure Tenant ID")
    use_managed_identity: bool = Field(
        default=False, description="Use ambient Azure Managed Identity"
    )

    @property
    def is_configured(self) -> bool:
        """Check if Azure credentials or ambient authentication are configured."""
        if self.use_managed_identity:
            return True
        return bool(self.tenant_id and self.client_id and self.client_secret)


class FederatedCspCredentialsConfig(BaseModel):
    """Aggregated credentials configuration for the Multi-CSP Free-Tier Mesh.

    Args:
        oci: OCI credentials configuration.
        aws: AWS credentials configuration.
        gcp: GCP credentials configuration.
        azure: Azure credentials configuration.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    aws: AwsCredentialsConfig = Field(
        default_factory=AwsCredentialsConfig, description="AWS credentials"
    )
    azure: AzureCredentialsConfig = Field(
        default_factory=AzureCredentialsConfig, description="Azure credentials"
    )
    gcp: GcpCredentialsConfig = Field(
        default_factory=GcpCredentialsConfig, description="GCP credentials"
    )
    oci: OciCredentialsConfig = Field(
        default_factory=OciCredentialsConfig, description="OCI credentials"
    )

    def is_provider_configured(self, provider: CspProvider) -> bool:
        """Check whether credentials are configured for target CSP.

        Args:
            provider: Target CspProvider enum.

        Returns:
            True if target provider has valid ambient or key-based credentials.
        """
        if provider in (CspProvider.LOCAL, CspProvider.ONPREM):
            return True
        if provider == CspProvider.OCI:
            return self.oci.is_configured
        if provider == CspProvider.AWS:
            return self.aws.is_configured
        if provider == CspProvider.GCP:
            return self.gcp.is_configured
        if provider == CspProvider.AZURE:
            return self.azure.is_configured
        return False

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
    ) -> Self:
        """Resolve CSP credentials securely from environment variables and .env files.

        Args:
            env: Optional dictionary of environment variables. When omitted, automatically
                discovers and merges .env.local and .env files under os.environ.
            cwd: Optional base directory to initiate .env upward discovery from.

        Returns:
            Configured FederatedCspCredentialsConfig instance.

        Notes/Architectural Intent:
            Checks Hexaqueue-prefixed variables first (HEXAQUEUE_OCI_*), falling back
            to standard cloud SDK conventions (AWS_ACCESS_KEY_ID, GOOGLE_APPLICATION_CREDENTIALS).
            Discovers local unversioned .env.local and .env files with zero external dependencies,
            preventing secret leakage while ensuring frictionless local developer ergonomics.
        """
        e = _discover_and_merge_env(cwd=cwd) if env is None else env

        # 1. OCI
        oci_key_content = e.get("HEXAQUEUE_OCI_KEY_CONTENT")
        oci = OciCredentialsConfig(
            fingerprint=e.get("HEXAQUEUE_OCI_FINGERPRINT")
            or e.get("OCI_CLI_FINGERPRINT"),
            key_content=SecretStr(oci_key_content) if oci_key_content else None,
            key_file=e.get("HEXAQUEUE_OCI_KEY_FILE") or e.get("OCI_CLI_KEY_FILE"),
            region=e.get("HEXAQUEUE_OCI_REGION")
            or e.get("OCI_CLI_REGION", "us-ashburn-1"),
            tenancy_ocid=e.get("HEXAQUEUE_OCI_TENANCY_OCID")
            or e.get("OCI_CLI_TENANCY"),
            use_instance_principals=_parse_bool(
                e.get("HEXAQUEUE_OCI_INSTANCE_PRINCIPALS")
            ),
            user_ocid=e.get("HEXAQUEUE_OCI_USER_OCID") or e.get("OCI_CLI_USER"),
        )

        # 2. AWS
        aws_key_id = e.get("HEXAQUEUE_AWS_ACCESS_KEY_ID") or e.get("AWS_ACCESS_KEY_ID")
        aws_secret = e.get("HEXAQUEUE_AWS_SECRET_ACCESS_KEY") or e.get(
            "AWS_SECRET_ACCESS_KEY"
        )
        aws_token = e.get("HEXAQUEUE_AWS_SESSION_TOKEN") or e.get("AWS_SESSION_TOKEN")
        aws = AwsCredentialsConfig(
            access_key_id=SecretStr(aws_key_id) if aws_key_id else None,
            profile=e.get("HEXAQUEUE_AWS_PROFILE") or e.get("AWS_PROFILE"),
            region=e.get("HEXAQUEUE_AWS_REGION")
            or e.get("AWS_DEFAULT_REGION")
            or e.get("AWS_REGION", "us-east-1"),
            secret_access_key=SecretStr(aws_secret) if aws_secret else None,
            session_token=SecretStr(aws_token) if aws_token else None,
            use_iam_role=_parse_bool(
                e.get("HEXAQUEUE_AWS_IAM_ROLE") or e.get("HEXAQUEUE_AWS_USE_IAM_ROLE")
            ),
        )

        # 3. GCP
        gcp_sa_json = e.get("HEXAQUEUE_GCP_SERVICE_ACCOUNT_JSON")
        gcp = GcpCredentialsConfig(
            project_id=e.get("HEXAQUEUE_GCP_PROJECT_ID")
            or e.get("GCP_PROJECT")
            or e.get("GOOGLE_CLOUD_PROJECT"),
            service_account_file=e.get("HEXAQUEUE_GCP_SERVICE_ACCOUNT_FILE")
            or e.get("GOOGLE_APPLICATION_CREDENTIALS"),
            service_account_json=SecretStr(gcp_sa_json) if gcp_sa_json else None,
            use_workload_identity=_parse_bool(e.get("HEXAQUEUE_GCP_WORKLOAD_IDENTITY")),
            zone=e.get("HEXAQUEUE_GCP_ZONE", "us-central1-a"),
        )

        # 4. Azure
        azure_secret = e.get("HEXAQUEUE_AZURE_CLIENT_SECRET") or e.get(
            "AZURE_CLIENT_SECRET"
        )
        azure = AzureCredentialsConfig(
            client_id=e.get("HEXAQUEUE_AZURE_CLIENT_ID") or e.get("AZURE_CLIENT_ID"),
            client_secret=SecretStr(azure_secret) if azure_secret else None,
            location=e.get("HEXAQUEUE_AZURE_LOCATION", "eastus"),
            subscription_id=e.get("HEXAQUEUE_AZURE_SUBSCRIPTION_ID")
            or e.get("AZURE_SUBSCRIPTION_ID"),
            tenant_id=e.get("HEXAQUEUE_AZURE_TENANT_ID") or e.get("AZURE_TENANT_ID"),
            use_managed_identity=_parse_bool(e.get("HEXAQUEUE_AZURE_MANAGED_IDENTITY")),
        )

        return cls(aws=aws, azure=azure, gcp=gcp, oci=oci)


__all__ = [
    "AwsCredentialsConfig",
    "AzureCredentialsConfig",
    "FederatedCspCredentialsConfig",
    "GcpCredentialsConfig",
    "OciCredentialsConfig",
]
