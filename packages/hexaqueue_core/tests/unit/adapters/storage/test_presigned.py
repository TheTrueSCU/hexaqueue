"""Unit tests for in-memory and local presigned object storage adapters."""

import tempfile
from pathlib import Path

import pytest

from hexaqueue_core.adapters.storage.presigned import (
    InMemoryPresignedStorageAdapter,
    LocalPresignedStorageAdapter,
)
from hexaqueue_core.domain.exceptions import HexaqueueError


@pytest.mark.asyncio
async def test_in_memory_presigned_storage_lifecycle() -> None:
    """Verify upload, download, metadata, and deletion in InMemoryPresignedStorageAdapter."""
    adapter = InMemoryPresignedStorageAdapter(endpoint_url="https://s3.mock.local")

    upload_url = await adapter.generate_presigned_upload_url(
        key="jobs/123/bundle.tar.gz",
        content_type="application/gzip",
        expires_in_seconds=1800,
    )
    assert "https://s3.mock.local/upload/jobs/123/bundle.tar.gz" in upload_url
    assert "expires=1800" in upload_url

    # Check non-existent before put
    exists_before = await adapter.object_exists("jobs/123/bundle.tar.gz")
    assert exists_before is False

    # Store payload
    payload = b"compressed-tar-data"
    adapter.put_object(
        "jobs/123/bundle.tar.gz",
        payload,
        metadata={"Retention": "ShortPass", "Owner": "ci-runner"},
    )

    exists_after = await adapter.object_exists("jobs/123/bundle.tar.gz")
    assert exists_after is True

    download_url = await adapter.generate_presigned_download_url(
        key="jobs/123/bundle.tar.gz",
        expires_in_seconds=900,
    )
    assert "https://s3.mock.local/download/jobs/123/bundle.tar.gz" in download_url
    assert "expires=900" in download_url

    retrieved = adapter.get_object("jobs/123/bundle.tar.gz")
    assert retrieved == payload

    meta = await adapter.get_object_metadata("jobs/123/bundle.tar.gz")
    assert meta["Retention"] == "ShortPass"
    assert meta["Owner"] == "ci-runner"

    # Delete
    await adapter.delete_object("jobs/123/bundle.tar.gz")
    exists_deleted = await adapter.object_exists("jobs/123/bundle.tar.gz")
    assert exists_deleted is False

    # Download of deleted object raises HexaqueueError
    with pytest.raises(HexaqueueError, match="not found"):
        await adapter.generate_presigned_download_url("jobs/123/bundle.tar.gz")


@pytest.mark.asyncio
async def test_local_presigned_storage_lifecycle() -> None:
    """Verify local filesystem-backed presigned storage adapter operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = LocalPresignedStorageAdapter(base_dir=tmpdir)

        upload_url = await adapter.generate_presigned_upload_url(
            key="logs/job-42/stdout.log",
            expires_in_seconds=3600,
        )
        assert upload_url.startswith("file://")
        assert "stdout.log" in upload_url

        # File does not exist yet
        exists_before = await adapter.object_exists("logs/job-42/stdout.log")
        assert exists_before is False

        # Simulate direct worker upload to target path
        target_path = Path(tmpdir) / "logs" / "job-42" / "stdout.log"
        target_path.write_bytes(b"hello world logs\n")

        exists_after = await adapter.object_exists("logs/job-42/stdout.log")
        assert exists_after is True

        download_url = await adapter.generate_presigned_download_url(
            key="logs/job-42/stdout.log",
            expires_in_seconds=600,
        )
        assert download_url == target_path.as_uri()

        meta = await adapter.get_object_metadata("logs/job-42/stdout.log")
        assert "size_bytes" in meta
        assert meta["size_bytes"] == str(len(b"hello world logs\n"))

        # Delete
        await adapter.delete_object("logs/job-42/stdout.log")
        exists_deleted = await adapter.object_exists("logs/job-42/stdout.log")
        assert exists_deleted is False
        assert not target_path.exists()


@pytest.mark.asyncio
async def test_local_presigned_storage_path_traversal_rejection() -> None:
    """Verify local presigned storage detects and rejects path traversal."""
    with tempfile.TemporaryDirectory() as tmpdir:
        adapter = LocalPresignedStorageAdapter(base_dir=tmpdir)
        with pytest.raises(HexaqueueError, match="Path traversal detected"):
            await adapter.generate_presigned_upload_url("../../../etc/passwd")
