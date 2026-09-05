"""Unit tests for storage volume port models and contracts."""

import pytest
from hexaqueue_core.ports.storage import VolumeAllocation


def test_volume_allocation_valid():
    """Verify VolumeAllocation creates valid model with constraints."""
    vol = VolumeAllocation(
        volume_id="vol-123",
        mount_path="/tmp/scratch/job-1",
        size_mb=1024,
        is_ephemeral=True,
    )
    assert vol.volume_id == "vol-123"
    assert vol.mount_path == "/tmp/scratch/job-1"
    assert vol.size_mb == 1024
    assert vol.is_ephemeral is True


def test_volume_allocation_invalid_invariants():
    """Verify VolumeAllocation rejects empty strings."""
    with pytest.raises(ValueError, match="volume_id cannot be empty"):
        VolumeAllocation(volume_id="   ", mount_path="/tmp", size_mb=100)

    with pytest.raises(ValueError, match="mount_path cannot be empty"):
        VolumeAllocation(volume_id="v1", mount_path="", size_mb=100)
