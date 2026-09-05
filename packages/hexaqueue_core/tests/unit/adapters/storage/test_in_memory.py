"""Unit tests for in-memory storage volume adapter."""

import pytest
from hexaqueue_core.adapters.storage.in_memory import InMemoryStorageVolumeAdapter


@pytest.mark.asyncio
async def test_in_memory_storage_lifecycle():
    """Verify temporary scratch allocation and cleanup."""
    storage = InMemoryStorageVolumeAdapter()
    vol = await storage.allocate_scratch(job_id="job-123", size_mb=512)

    assert vol.size_mb == 512
    assert "hq-scratch-job-123" in vol.mount_path

    await storage.cleanup_scratch(vol.volume_id)
