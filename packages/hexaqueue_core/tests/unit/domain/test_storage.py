"""Unit tests for storage domain models and volume mounts."""

import pytest
from pydantic import ValidationError

from hexaqueue_core.domain.storage import FilesystemType, SharedVolumeMount


def test_shared_volume_mount_defaults_and_properties() -> None:
    """Verify default values and attributes of SharedVolumeMount."""
    mount = SharedVolumeMount(
        name="datasets",
        source_path="/nfs/shared/datasets",
        mount_path="/mnt/datasets",
        filesystem_type=FilesystemType.NFS,
        read_only=True,
    )
    name = mount.name
    src = mount.source_path
    dst = mount.mount_path
    fs_type = mount.filesystem_type
    ro = mount.read_only

    assert name == "datasets"
    assert src == "/nfs/shared/datasets"
    assert dst == "/mnt/datasets"
    assert fs_type == FilesystemType.NFS
    assert ro is True


def test_shared_volume_mount_default_filesystem() -> None:
    """Verify default filesystem is LOCAL_POSIX and read_only is False."""
    mount = SharedVolumeMount(
        name="scratch",
        source_path="/scratch",
        mount_path="/scratch",
    )
    fs_type = mount.filesystem_type
    ro = mount.read_only

    assert fs_type == FilesystemType.LOCAL_POSIX
    assert ro is False


def test_shared_volume_mount_validation_errors() -> None:
    """Verify validation on empty strings for name or paths."""
    with pytest.raises(ValidationError):
        SharedVolumeMount(name="", source_path="/a", mount_path="/b")

    with pytest.raises(ValidationError):
        SharedVolumeMount(name="vol", source_path="", mount_path="/b")

    with pytest.raises(ValidationError):
        SharedVolumeMount(name="vol", source_path="/a", mount_path="")
