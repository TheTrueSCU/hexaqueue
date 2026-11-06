"""Oracle Cloud Infrastructure (OCI) Object Storage presigned URL and CAS adapter.

Notes/Architectural Intent:
    Implements PresignedStoragePort for Oracle Cloud Infrastructure (OCI) Object
    Storage. Provides time-bounded Pre-Authenticated Requests (PARs) for direct
    collateral bundle and test coverage artifact upload and download. Operates
    hermetically with mock injection or live via instance principals and tenancy credentials.
"""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from hexaqueue_core.domain.credentials import OciCredentialsConfig
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.ports.storage import PresignedStoragePort
from hexaqueue_core.utils.imports import optional_dependency


class OciPresignedStorageAdapter(PresignedStoragePort):
    """Adapter for governing OCI Object Storage Pre-Authenticated Requests (PARs).

    Args:
        object_storage_client: Injected OCI ObjectStorageClient or mock.
        namespace: OCI Object Storage tenancy namespace.
        bucket_name: Target bucket name for collateral and coverage artifacts.
        region: OCI region identifier (e.g. us-phoenix-1).
        credentials: Optional OciCredentialsConfig for SDK configuration.

    Notes/Architectural Intent:
        Hermetically testable through client injection and in-memory simulated objects
        without requiring live OCI tenancy credentials or network access. All blocking
        OCI SDK calls are executed via asyncio.to_thread to maintain event loop concurrency.
    """

    def __init__(
        self,
        object_storage_client: Any = None,
        namespace: str = "ax8nkvebgihr",
        bucket_name: str = "hexaqueue-collateral",
        region: str = "us-phoenix-1",
        credentials: OciCredentialsConfig | None = None,
    ) -> None:
        self._client = object_storage_client
        self._namespace = namespace
        self._bucket_name = bucket_name
        self._region = region
        self._credentials = credentials

        # Hermetic in-memory simulation state when live client is omitted
        self._simulated_objects: dict[str, bytes] = {}
        self._simulated_metadata: dict[str, dict[str, str]] = {}

    @property
    def namespace(self) -> str:
        """Return the configured Object Storage namespace."""
        return self._namespace

    @property
    def bucket_name(self) -> str:
        """Return the target Object Storage bucket name."""
        return self._bucket_name

    @property
    def region(self) -> str:
        """Return the configured OCI region identifier."""
        return self._region

    @classmethod
    def from_credentials(
        cls,
        credentials: OciCredentialsConfig | None = None,
        namespace: str | None = None,
        bucket_name: str | None = None,
        region: str | None = None,
    ) -> "OciPresignedStorageAdapter":
        """Factory creating an adapter from OCI credentials.

        Args:
            credentials: Optional OCI credentials configuration.
            namespace: Optional namespace override.
            bucket_name: Optional bucket name override.
            region: Optional region override.

        Returns:
            Configured OciPresignedStorageAdapter instance.

        Notes/Architectural Intent:
            Attempts to configure live OCI SDK ObjectStorageClient if the oci
            package is installed and credentials are configured; otherwise
            falls back gracefully to hermetic simulation mode.
        """
        client = None
        oci_mod = optional_dependency("oci")

        ns = namespace or "ax8nkvebgihr"
        b_name = bucket_name or "hexaqueue-collateral"
        r_name = region or "us-phoenix-1"

        if (
            oci_mod is not None
            and credentials is not None
            and credentials.is_configured
        ):
            try:
                if credentials.use_instance_principals:
                    signer = (
                        oci_mod.auth.signers.InstancePrincipalsSecurityTokenSigner()
                    )
                    client = oci_mod.object_storage.ObjectStorageClient(
                        config={}, signer=signer
                    )
                elif (
                    credentials.key_content is not None
                    or credentials.key_file is not None
                ):
                    sdk_config = {
                        "user": credentials.user_ocid or "",
                        "fingerprint": credentials.fingerprint or "",
                        "tenancy": credentials.tenancy_ocid or "",
                        "region": credentials.region or "us-ashburn-1",
                    }
                    if credentials.key_content is not None:
                        sdk_config["key_content"] = (
                            credentials.key_content.get_secret_value()
                        )
                    elif credentials.key_file is not None:
                        sdk_config["key_file"] = credentials.key_file
                    client = oci_mod.object_storage.ObjectStorageClient(sdk_config)
                    if not region and credentials.region:
                        r_name = credentials.region
            except Exception:
                client = None

        return cls(
            object_storage_client=client,
            namespace=ns,
            bucket_name=b_name,
            region=r_name,
            credentials=credentials,
        )

    async def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str | None = None,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Generate a time-bounded presigned upload URL (OCI PAR) for direct upload.

        Args:
            key: Target object key in bucket.
            content_type: Optional expected MIME type.
            expires_in_seconds: Expiration lifetime in seconds (default 1 hour).

        Returns:
            Preauthenticated upload URL string.

        Raises:
            HexaqueueError: If PAR generation encounters an error.

        Notes/Architectural Intent:
            Creates an ObjectWrite Pre-Authenticated Request in OCI Object Storage.
        """
        clean_key = key.lstrip("/")

        if self._client is not None:
            oci_mod = optional_dependency("oci")
            if oci_mod is None:
                msg = "OCI SDK required for live Pre-Authenticated Request generation"
                raise HexaqueueError(msg)

            expires_at = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)
            par_name = f"par-up-{uuid4().hex[:8]}"

            details = (
                oci_mod.object_storage.models.CreatePreauthenticatedRequestDetails(
                    name=par_name,
                    object_name=clean_key,
                    access_type="ObjectWrite",
                    time_expires=expires_at,
                )
            )

            try:
                resp = await asyncio.to_thread(
                    self._client.create_preauthenticated_request,
                    namespace_name=self._namespace,
                    bucket_name=self._bucket_name,
                    create_preauthenticated_request_details=details,
                )
                access_uri = resp.data.access_uri
                return (
                    f"https://objectstorage.{self._region}.oraclecloud.com{access_uri}"
                )
            except Exception as exc:
                msg = f"Failed to generate OCI presigned upload PAR for '{clean_key}': {exc}"
                raise HexaqueueError(msg) from exc

        # Simulated virtual endpoint
        return (
            f"https://objectstorage.{self._region}.oraclecloud.com/p/sim-up/"
            f"n/{self._namespace}/b/{self._bucket_name}/o/{clean_key}?expires={expires_in_seconds}"
        )

    async def generate_presigned_download_url(
        self,
        key: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Generate a time-bounded presigned download URL (OCI PAR) for direct download.

        Args:
            key: Object key to download.
            expires_in_seconds: Expiration lifetime in seconds (default 1 hour).

        Returns:
            Preauthenticated download URL string.

        Raises:
            HexaqueueError: If object is not found or PAR generation fails.

        Notes/Architectural Intent:
            Enforces existence verification before issuing read PARs to conform to port contracts.
        """
        clean_key = key.lstrip("/")
        exists = await self.object_exists(clean_key)
        if not exists:
            msg = f"Object '{clean_key}' not found in OCI Object Storage bucket '{self._bucket_name}'"
            raise HexaqueueError(msg)

        if self._client is not None:
            oci_mod = optional_dependency("oci")
            if oci_mod is None:
                msg = "OCI SDK required for live Pre-Authenticated Request generation"
                raise HexaqueueError(msg)

            expires_at = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)
            par_name = f"par-dn-{uuid4().hex[:8]}"

            details = (
                oci_mod.object_storage.models.CreatePreauthenticatedRequestDetails(
                    name=par_name,
                    object_name=clean_key,
                    access_type="ObjectRead",
                    time_expires=expires_at,
                )
            )

            try:
                resp = await asyncio.to_thread(
                    self._client.create_preauthenticated_request,
                    namespace_name=self._namespace,
                    bucket_name=self._bucket_name,
                    create_preauthenticated_request_details=details,
                )
                access_uri = resp.data.access_uri
                return (
                    f"https://objectstorage.{self._region}.oraclecloud.com{access_uri}"
                )
            except Exception as exc:
                msg = f"Failed to generate OCI presigned download PAR for '{clean_key}': {exc}"
                raise HexaqueueError(msg) from exc

        return (
            f"https://objectstorage.{self._region}.oraclecloud.com/p/sim-dn/"
            f"n/{self._namespace}/b/{self._bucket_name}/o/{clean_key}?expires={expires_in_seconds}"
        )

    async def object_exists(self, key: str) -> bool:
        """Check whether an object exists in the OCI bucket.

        Args:
            key: Target object key.

        Returns:
            True if present, False otherwise.

        Raises:
            HexaqueueError: If unexpected error occurs during inspection.

        Notes/Architectural Intent:
            Leverages HEAD object request to minimize network transfer.
        """
        clean_key = key.lstrip("/")

        if self._client is not None:
            try:
                await asyncio.to_thread(
                    self._client.head_object,
                    namespace_name=self._namespace,
                    bucket_name=self._bucket_name,
                    object_name=clean_key,
                )
                return True
            except Exception as exc:
                # ServiceError status 404 indicates missing object
                status = getattr(exc, "status", None)
                if status == 404 or "NotAuthorizedOrNotFound" in str(exc):
                    return False
                msg = f"Error querying OCI Object Storage for '{clean_key}': {exc}"
                raise HexaqueueError(msg) from exc

        return clean_key in self._simulated_objects

    async def get_object_metadata(self, key: str) -> dict[str, str]:
        """Retrieve metadata tags and headers for an object.

        Args:
            key: Target object key.

        Returns:
            Dictionary of string metadata pairs.

        Raises:
            HexaqueueError: If object is not found or inspection fails.
        """
        clean_key = key.lstrip("/")

        if self._client is not None:
            try:
                resp = await asyncio.to_thread(
                    self._client.head_object,
                    namespace_name=self._namespace,
                    bucket_name=self._bucket_name,
                    object_name=clean_key,
                )
                raw_headers: Mapping[str, Any] = getattr(resp, "headers", {})
                return {str(k).lower(): str(v) for k, v in raw_headers.items()}
            except Exception as exc:
                msg = f"Failed to retrieve metadata for '{clean_key}': {exc}"
                raise HexaqueueError(msg) from exc

        if clean_key not in self._simulated_objects:
            msg = f"Object '{clean_key}' not found in simulation storage"
            raise HexaqueueError(msg)

        return self._simulated_metadata.get(
            clean_key, {"content-length": str(len(self._simulated_objects[clean_key]))}
        )

    async def delete_object(self, key: str) -> None:
        """Delete an object from OCI Object Storage bucket.

        Args:
            key: Target object key.

        Raises:
            HexaqueueError: If deletion fails.
        """
        clean_key = key.lstrip("/")

        if self._client is not None:
            try:
                await asyncio.to_thread(
                    self._client.delete_object,
                    namespace_name=self._namespace,
                    bucket_name=self._bucket_name,
                    object_name=clean_key,
                )
                return
            except Exception as exc:
                msg = f"Failed to delete OCI object '{clean_key}': {exc}"
                raise HexaqueueError(msg) from exc

        self._simulated_objects.pop(clean_key, None)
        self._simulated_metadata.pop(clean_key, None)

    async def put_object(
        self,
        key: str,
        data: bytes,
        content_type: str | None = None,
    ) -> None:
        """Directly upload raw bytes into OCI Object Storage bucket.

        Args:
            key: Target object key.
            data: Binary payload to upload.
            content_type: Optional MIME content type.

        Raises:
            HexaqueueError: If direct upload fails.

        Notes/Architectural Intent:
            Used by controller during CAS promotion and by workers when uploading coverage.
        """
        clean_key = key.lstrip("/")

        if self._client is not None:
            kwargs: dict[str, Any] = {}
            if content_type:
                kwargs["content_type"] = content_type

            try:
                await asyncio.to_thread(
                    self._client.put_object,
                    namespace_name=self._namespace,
                    bucket_name=self._bucket_name,
                    object_name=clean_key,
                    put_object_body=data,
                    **kwargs,
                )
                return
            except Exception as exc:
                msg = f"Failed to put OCI object '{clean_key}': {exc}"
                raise HexaqueueError(msg) from exc

        self._simulated_objects[clean_key] = data
        self._simulated_metadata[clean_key] = {
            "content-length": str(len(data)),
            "content-type": content_type or "application/octet-stream",
        }

    async def get_object_bytes(self, key: str) -> bytes:
        """Directly retrieve raw bytes of an object from OCI Object Storage.

        Args:
            key: Target object key.

        Returns:
            Binary object content.

        Raises:
            HexaqueueError: If object is missing or retrieval fails.
        """
        clean_key = key.lstrip("/")

        if self._client is not None:
            try:
                resp = await asyncio.to_thread(
                    self._client.get_object,
                    namespace_name=self._namespace,
                    bucket_name=self._bucket_name,
                    object_name=clean_key,
                )
                content = getattr(resp.data, "content", None)
                if content is not None:
                    return bytes(content)
                text = getattr(resp.data, "text", "")
                return str(text).encode("utf-8")
            except Exception as exc:
                msg = f"Failed to retrieve OCI object '{clean_key}': {exc}"
                raise HexaqueueError(msg) from exc

        if clean_key not in self._simulated_objects:
            msg = f"Object '{clean_key}' not found in simulation storage"
            raise HexaqueueError(msg)

        return self._simulated_objects[clean_key]


__all__ = [
    "OciPresignedStorageAdapter",
]
