"""Unit tests for local disk storage volume adapter."""

import pytest
from hexaqueue_core.adapters.storage.local import LocalDiskStorageVolumeAdapter


@pytest.mark.asyncio
async def test_local_disk_storage_lifecycle():
    """Verify temporary scratch allocation and cleanup on local disk."""
    storage = LocalDiskStorageVolumeAdapter()
    vol = await storage.allocate_scratch(job_id="job-456", size_mb=256)

    assert vol.size_mb == 256
    assert "hq-scratch-job-456" in vol.mount_path

    await storage.cleanup_scratch(vol.volume_id)
