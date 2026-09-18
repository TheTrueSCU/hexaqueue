"""Unit tests for NvmeScratchStorageVolumeAdapter and cache preservation."""

import tempfile
from pathlib import Path

import pytest

from hexaqueue_core.domain.exceptions import StorageVolumeError
from hexaqueue_core.domain.storage import FilesystemType, SharedVolumeMount
from hexaqueue_worker.adapters.storage import NvmeScratchStorageVolumeAdapter


@pytest.mark.asyncio
async def test_scratch_allocation_and_cleanup() -> None:
    """Verify scratch directory allocation, volume metadata, and cleanup."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        adapter = NvmeScratchStorageVolumeAdapter(base_scratch_dir=tmp_dir)

        # Allocate scratch volume
        vol = await adapter.allocate_scratch(job_id="job-42", size_mb=10)
        vol_id = vol.volume_id
        mount_path = Path(vol.mount_path)
        is_ephemeral = vol.is_ephemeral

        assert vol_id.startswith("vol-scratch-")
        assert is_ephemeral is True
        exists_before = mount_path.exists()
        assert exists_before is True

        # Clean up scratch volume
        await adapter.cleanup_scratch(vol_id)
        exists_after = mount_path.exists()
        assert exists_after is False


@pytest.mark.asyncio
async def test_scratch_cleanup_preserves_collateral_cache() -> None:
    """Verify that scratch cleanup preserves warm collateral cache directory and files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        adapter = NvmeScratchStorageVolumeAdapter(base_scratch_dir=tmp_dir)

        # Populate collateral cache file
        cache_dir = adapter.collateral_cache_dir
        cached_file = cache_dir / "weights.pt"
        cached_file.write_text("warm collateral data")

        # Allocate and cleanup job scratch
        vol = await adapter.allocate_scratch(job_id="job-cache-test", size_mb=10)
        await adapter.cleanup_scratch(vol.volume_id)

        # Verify warm cache remains intact
        cache_exists = cached_file.exists()
        content = cached_file.read_text()
        assert cache_exists is True
        assert content == "warm collateral data"


@pytest.mark.asyncio
async def test_scratch_allocation_quota_exceeded() -> None:
    """Verify StorageVolumeError when requested size exceeds available filesystem capacity."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        adapter = NvmeScratchStorageVolumeAdapter(base_scratch_dir=tmp_dir)

        # Request 100 Petabytes
        with pytest.raises(StorageVolumeError, match="Insufficient scratch storage"):
            await adapter.allocate_scratch(job_id="huge-job", size_mb=100_000_000_000)


def test_shared_mounts_validation() -> None:
    """Verify validation of shared volume mounts against filesystem existence."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        valid_mount = SharedVolumeMount(
            name="shared-data",
            source_path=tmp_dir,
            mount_path="/mnt/shared",
            filesystem_type=FilesystemType.LOCAL_POSIX,
        )
        adapter = NvmeScratchStorageVolumeAdapter(
            base_scratch_dir=tmp_dir,
            shared_mounts=[valid_mount],
        )
        validated = adapter.validate_shared_mounts()
        count = len(validated)
        assert count == 1

        # Non-existent source path
        invalid_mount = SharedVolumeMount(
            name="bad-share",
            source_path="/non/existent/nfs/share/xyz123",
            mount_path="/mnt/bad",
        )
        adapter_bad = NvmeScratchStorageVolumeAdapter(
            base_scratch_dir=tmp_dir,
            shared_mounts=[invalid_mount],
        )
        with pytest.raises(
            StorageVolumeError, match="Shared mount source path does not exist"
        ):
            adapter_bad.validate_shared_mounts()


def test_scratch_adapter_default_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify default base directory resolution including /scratch fallback."""
    # When /scratch is not a directory
    adapter_default = NvmeScratchStorageVolumeAdapter()
    base_default = adapter_default.base_dir
    assert "hexaqueue_scratch" in str(base_default)

    # When /scratch is mocked as an existing directory
    monkeypatch.setattr(Path, "is_dir", lambda self: str(self) == "/scratch")
    adapter_scratch = NvmeScratchStorageVolumeAdapter()
    base_scratch = adapter_scratch.base_dir
    assert str(base_scratch) == "/scratch"


@pytest.mark.asyncio
async def test_scratch_allocation_os_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify StorageVolumeError on unexpected OSError during disk usage check."""
    import shutil

    with tempfile.TemporaryDirectory() as tmp_dir:
        adapter = NvmeScratchStorageVolumeAdapter(base_scratch_dir=tmp_dir)

        def mock_disk_usage(path):
            raise OSError("disk failure")

        monkeypatch.setattr(shutil, "disk_usage", mock_disk_usage)

        with pytest.raises(StorageVolumeError, match="Failed to verify scratch quota"):
            await adapter.allocate_scratch(job_id="err-job", size_mb=10)
