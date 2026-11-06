"""Hermetic unit tests for OCI Object Storage presigned storage adapter.

Notes/Architectural Intent:
    Verifies OciPresignedStorageAdapter in both offline hermetic simulation mode
    and injected mock client mode. All assertion returns are captured into variables
    first to prevent CodeQL side-effect warnings.
"""

from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from hexaqueue_core.adapters.storage.oci import OciPresignedStorageAdapter
from hexaqueue_core.domain.credentials import OciCredentialsConfig
from hexaqueue_core.domain.exceptions import HexaqueueError


@pytest.mark.asyncio
async def test_oci_storage_simulation_mode_lifecycle() -> None:
    """Verify in-memory simulation mode when client is omitted."""
    adapter = OciPresignedStorageAdapter(
        namespace="test-ns",
        bucket_name="test-bucket",
        region="us-phoenix-1",
    )

    ns_val = adapter.namespace
    b_val = adapter.bucket_name
    r_val = adapter.region
    assert ns_val == "test-ns"
    assert b_val == "test-bucket"
    assert r_val == "us-phoenix-1"

    # Missing object initially
    initial_exists = await adapter.object_exists("collateral/workspace.tar.gz")
    assert initial_exists is False

    # Direct upload in simulation
    payload = b"workspace-archive-payload"
    await adapter.put_object("collateral/workspace.tar.gz", payload)

    exists_after_put = await adapter.object_exists("collateral/workspace.tar.gz")
    assert exists_after_put is True

    retrieved = await adapter.get_object_bytes("collateral/workspace.tar.gz")
    assert retrieved == payload

    meta = await adapter.get_object_metadata("collateral/workspace.tar.gz")
    length_val = meta.get("content-length")
    assert length_val == str(len(payload))

    # Presigned URLs
    up_url = await adapter.generate_presigned_upload_url("collateral/new.tar.gz")
    assert "objectstorage.us-phoenix-1.oraclecloud.com" in up_url
    assert "test-bucket" in up_url

    dn_url = await adapter.generate_presigned_download_url(
        "collateral/workspace.tar.gz"
    )
    assert "objectstorage.us-phoenix-1.oraclecloud.com" in dn_url
    assert "test-bucket" in dn_url

    # Deletion
    await adapter.delete_object("collateral/workspace.tar.gz")
    exists_after_del = await adapter.object_exists("collateral/workspace.tar.gz")
    assert exists_after_del is False

    # Download missing raises HexaqueueError
    with pytest.raises(HexaqueueError, match="not found"):
        await adapter.generate_presigned_download_url("collateral/workspace.tar.gz")

    with pytest.raises(HexaqueueError, match="not found"):
        await adapter.get_object_metadata("collateral/workspace.tar.gz")

    with pytest.raises(HexaqueueError, match="not found"):
        await adapter.get_object_bytes("collateral/workspace.tar.gz")


@pytest.mark.asyncio
async def test_oci_storage_from_credentials_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify factory initializes properly with or without configured credentials."""
    unconfigured = OciPresignedStorageAdapter.from_credentials(None)
    assert unconfigured.namespace == "ax8nkvebgihr"
    assert unconfigured.bucket_name == "hexaqueue-collateral"

    # Instance principals branch
    mock_oci = MagicMock()
    monkeypatch.setattr(
        "hexaqueue_core.adapters.storage.oci.optional_dependency",
        lambda name: mock_oci if name == "oci" else None,
    )

    ip_creds = OciCredentialsConfig(use_instance_principals=True)
    ip_adapter = OciPresignedStorageAdapter.from_credentials(ip_creds)
    assert ip_adapter._client is not None
    assert mock_oci.auth.signers.InstancePrincipalsSecurityTokenSigner.call_count == 1

    # Key file and key content branch
    key_creds = OciCredentialsConfig(
        tenancy_ocid="ocid1.tenancy.oc1..test",
        user_ocid="ocid1.user.oc1..test",
        fingerprint="test-fp",
        key_content=SecretStr("mock-key"),
        region="us-phoenix-1",
    )
    key_adapter = OciPresignedStorageAdapter.from_credentials(key_creds)
    assert key_adapter._client is not None
    assert key_adapter.region == "us-phoenix-1"

    # Key file fallback
    file_creds = OciCredentialsConfig(
        tenancy_ocid="ocid1.tenancy.oc1..test",
        user_ocid="ocid1.user.oc1..test",
        fingerprint="test-fp",
        key_file="/path/to/key.pem",
        region="us-ashburn-1",
    )
    file_adapter = OciPresignedStorageAdapter.from_credentials(file_creds)
    assert file_adapter._client is not None


@pytest.mark.asyncio
async def test_oci_storage_with_injected_mock_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify adapter delegates properly when live client is injected."""
    mock_client = MagicMock()

    # Mock PAR response
    mock_par_resp = MagicMock()
    mock_par_resp.data.access_uri = (
        "/p/test-par-token/n/test-ns/b/test-bucket/o/collateral/target.tar.gz"
    )
    mock_client.create_preauthenticated_request.return_value = mock_par_resp

    # Mock HEAD response
    mock_head_resp = MagicMock()
    mock_head_resp.headers = {
        "content-length": "42",
        "content-type": "application/octet-stream",
    }
    mock_client.head_object.return_value = mock_head_resp

    # Mock GET response
    mock_get_resp = MagicMock()
    mock_get_resp.data.content = b"downloaded-bytes"
    mock_client.get_object.return_value = mock_get_resp

    # Inject mock oci module so CreatePreauthenticatedRequestDetails is accessible
    mock_oci = MagicMock()
    monkeypatch.setattr(
        "hexaqueue_core.adapters.storage.oci.optional_dependency",
        lambda name: mock_oci if name == "oci" else None,
    )

    adapter = OciPresignedStorageAdapter(
        object_storage_client=mock_client,
        namespace="test-ns",
        bucket_name="test-bucket",
        region="us-phoenix-1",
    )

    # 1. Upload PAR
    up_url = await adapter.generate_presigned_upload_url("collateral/target.tar.gz")
    assert (
        up_url
        == "https://objectstorage.us-phoenix-1.oraclecloud.com/p/test-par-token/n/test-ns/b/test-bucket/o/collateral/target.tar.gz"
    )
    assert mock_client.create_preauthenticated_request.call_count == 1

    # 2. Exists
    exists_val = await adapter.object_exists("collateral/target.tar.gz")
    assert exists_val is True
    assert mock_client.head_object.call_count == 1

    # 3. Download PAR
    dn_url = await adapter.generate_presigned_download_url("collateral/target.tar.gz")
    assert (
        dn_url
        == "https://objectstorage.us-phoenix-1.oraclecloud.com/p/test-par-token/n/test-ns/b/test-bucket/o/collateral/target.tar.gz"
    )
    assert mock_client.create_preauthenticated_request.call_count == 2

    # 4. Metadata
    meta = await adapter.get_object_metadata("collateral/target.tar.gz")
    assert meta["content-length"] == "42"

    # 5. Direct Put and Get
    await adapter.put_object(
        "collateral/target.tar.gz", b"new-payload", content_type="application/tar"
    )
    assert mock_client.put_object.call_count == 1

    content = await adapter.get_object_bytes("collateral/target.tar.gz")
    assert content == b"downloaded-bytes"
    assert mock_client.get_object.call_count == 1

    # 6. Direct Get with text fallback
    mock_get_text_resp = MagicMock()
    mock_get_text_resp.data.content = None
    mock_get_text_resp.data.text = "text-payload"
    mock_client.get_object.return_value = mock_get_text_resp
    text_content = await adapter.get_object_bytes("collateral/target.tar.gz")
    assert text_content == b"text-payload"

    # 7. Delete
    await adapter.delete_object("collateral/target.tar.gz")
    assert mock_client.delete_object.call_count == 1


@pytest.mark.asyncio
async def test_oci_storage_client_error_handling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify error handling and 404 translation when client raises."""
    mock_client = MagicMock()

    class NotFoundServiceError(Exception):
        def __init__(self) -> None:
            self.status = 404

    class TransportError(Exception):
        pass

    mock_client.head_object.side_effect = NotFoundServiceError()

    mock_oci = MagicMock()
    monkeypatch.setattr(
        "hexaqueue_core.adapters.storage.oci.optional_dependency",
        lambda name: mock_oci if name == "oci" else None,
    )

    adapter = OciPresignedStorageAdapter(
        object_storage_client=mock_client,
        namespace="test-ns",
        bucket_name="test-bucket",
    )

    # 404 turns into False
    exists_val = await adapter.object_exists("missing.tar.gz")
    assert exists_val is False

    # Transport error in head_object raises HexaqueueError
    mock_client.head_object.side_effect = TransportError("Network down")
    with pytest.raises(HexaqueueError, match="Error querying OCI Object Storage"):
        await adapter.object_exists("error.tar.gz")

    # Error in create_preauthenticated_request raises HexaqueueError
    mock_client.create_preauthenticated_request.side_effect = TransportError(
        "Permission denied"
    )
    with pytest.raises(
        HexaqueueError, match="Failed to generate OCI presigned upload PAR"
    ):
        await adapter.generate_presigned_upload_url("target.tar.gz")

    # Error in metadata retrieval
    mock_client.head_object.side_effect = TransportError("Metadata fetch failed")
    with pytest.raises(HexaqueueError, match="Failed to retrieve metadata"):
        await adapter.get_object_metadata("target.tar.gz")

    # Error in delete
    mock_client.delete_object.side_effect = TransportError("Delete failed")
    with pytest.raises(HexaqueueError, match="Failed to delete OCI object"):
        await adapter.delete_object("target.tar.gz")

    # Error in put_object
    mock_client.put_object.side_effect = TransportError("Upload failed")
    with pytest.raises(HexaqueueError, match="Failed to put OCI object"):
        await adapter.put_object("target.tar.gz", b"data")

    # Error in get_object
    mock_client.get_object.side_effect = TransportError("Download failed")
    with pytest.raises(HexaqueueError, match="Failed to retrieve OCI object"):
        await adapter.get_object_bytes("target.tar.gz")


@pytest.mark.asyncio
async def test_oci_storage_missing_sdk_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify HexaqueueError is raised if client is configured but SDK is unimportable."""
    mock_client = MagicMock()
    mock_client.head_object.return_value = MagicMock()

    monkeypatch.setattr(
        "hexaqueue_core.adapters.storage.oci.optional_dependency",
        lambda name: None,
    )

    adapter = OciPresignedStorageAdapter(
        object_storage_client=mock_client,
        namespace="test-ns",
        bucket_name="test-bucket",
    )

    with pytest.raises(HexaqueueError, match="OCI SDK required"):
        await adapter.generate_presigned_upload_url("target.tar.gz")

    with pytest.raises(HexaqueueError, match="OCI SDK required"):
        await adapter.generate_presigned_download_url("target.tar.gz")
