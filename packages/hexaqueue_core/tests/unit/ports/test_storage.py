"""Tests for StorageVolumePort and VolumeAllocation."""

import pytest

from hexaqueue_core.ports.storage import StorageVolumePort, VolumeAllocation


def test_storage_volume_port_is_abstract() -> None:
    """Verify StorageVolumePort cannot be instantiated directly."""
    with pytest.raises(TypeError):
        StorageVolumePort()  # type: ignore[abstract]


def test_volume_allocation_model() -> None:
    """Verify VolumeAllocation model and validation."""
    vol = VolumeAllocation(volume_id="vol-1", mount_path="/mnt/scratch", size_mb=1024)
    assert vol.volume_id == "vol-1"
    assert vol.mount_path == "/mnt/scratch"
    assert vol.size_mb == 1024
    assert vol.is_ephemeral is True

    with pytest.raises(ValueError, match="volume_id cannot be empty"):
        VolumeAllocation(volume_id="  ", mount_path="/mnt/scratch", size_mb=1024)

    with pytest.raises(ValueError, match="mount_path cannot be empty"):
        VolumeAllocation(volume_id="vol-1", mount_path="  ", size_mb=1024)
