"""NVMe and local filesystem scratch storage adapter with quota validation.

Notes/Architectural Intent:
    Allocates isolated temporary scratch directories per job execution (e.g. /scratch/hq-$JOB_ID).
    Validates storage capacity against required quotas via filesystem disk usage metrics.
    Ensures safe, leak-free post-job cleanup while strictly preserving adjacent shared volumes
    and warm collateral cache directories.
"""

import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from hexaqueue_core.domain.exceptions import StorageVolumeError
from hexaqueue_core.domain.storage import SharedVolumeMount
from hexaqueue_core.ports.storage import StorageVolumePort, VolumeAllocation


class NvmeScratchStorageVolumeAdapter(StorageVolumePort):
    """Local scratch storage volume adapter supporting quota validation and cache preservation.

    Args:
        base_scratch_dir: Base directory path for scratch allocations. Defaults to
            /scratch if accessible, or system temporary directory otherwise.
        shared_mounts: Optional list of SharedVolumeMount configurations available to jobs.
        preserve_cache_dirname: Subdirectory name within base_scratch_dir reserved for
            warm collateral caching that must never be deleted by job teardown.
    """

    def __init__(
        self,
        base_scratch_dir: str | None = None,
        shared_mounts: list[SharedVolumeMount] | None = None,
        preserve_cache_dirname: str = "collateral_cache",
    ) -> None:
        if base_scratch_dir:
            self._base_dir = Path(base_scratch_dir)
        elif Path("/scratch").is_dir():
            self._base_dir = Path("/scratch")
        else:
            self._base_dir = Path(tempfile.gettempdir()) / "hexaqueue_scratch"

        self._shared_mounts = shared_mounts or []
        self._preserve_cache_dirname = preserve_cache_dirname
        self._allocations: dict[str, Path] = {}

    @property
    def base_dir(self) -> Path:
        """Return the resolved base scratch filesystem root directory."""
        return self._base_dir

    @property
    def collateral_cache_dir(self) -> Path:
        """Return the reserved warm collateral cache directory."""
        cache_dir = self._base_dir / self._preserve_cache_dirname
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    async def allocate_scratch(
        self, job_id: str, size_mb: int, base_dir: str | None = None
    ) -> VolumeAllocation:
        """Allocate an isolated scratch storage volume with quota verification.

        Args:
            job_id: Unique job identifier.
            size_mb: Required scratch disk capacity in megabytes.
            base_dir: Optional base path override.

        Returns:
            VolumeAllocation metadata describing the allocated scratch directory.

        Raises:
            StorageVolumeError: If remaining filesystem capacity is insufficient.
        """
        root = Path(base_dir) if base_dir else self._base_dir
        root.mkdir(parents=True, exist_ok=True)

        # Quota verification
        try:
            usage = shutil.disk_usage(root)
            free_mb = usage.free // (1024 * 1024)
            if size_mb > free_mb:
                msg = (
                    f"Insufficient scratch storage for job '{job_id}': "
                    f"requested {size_mb} MB, available {free_mb} MB"
                )
                raise StorageVolumeError(msg)
        except OSError as exc:
            msg = f"Failed to verify scratch quota on '{root}': {exc}"
            raise StorageVolumeError(msg) from exc

        mount_path = Path(tempfile.mkdtemp(prefix=f"hq-scratch-{job_id}-", dir=root))
        volume_id = f"vol-scratch-{uuid4().hex[:8]}"
        self._allocations[volume_id] = mount_path

        return VolumeAllocation(
            volume_id=volume_id,
            mount_path=str(mount_path),
            size_mb=size_mb,
            is_ephemeral=True,
        )

    async def cleanup_scratch(self, volume_id: str) -> None:
        """Purge temporary scratch storage directory while preserving cache.

        Args:
            volume_id: Unique volume identifier to reclaim.
        """
        if volume_id in self._allocations:
            mount_path = self._allocations.pop(volume_id)
            # Guard against deleting the base directory or warm cache directory
            if (
                mount_path != self._base_dir
                and mount_path != self.collateral_cache_dir
                and mount_path.exists()
            ):
                shutil.rmtree(mount_path, ignore_errors=True)

    def validate_shared_mounts(self) -> list[SharedVolumeMount]:
        """Verify that configured shared volume mounts exist on the host filesystem.

        Returns:
            List of validated SharedVolumeMount configurations.

        Raises:
            StorageVolumeError: If any mandatory shared mount source path does not exist.
        """
        for mount in self._shared_mounts:
            src = Path(mount.source_path)
            if not src.exists():
                msg = f"Shared mount source path does not exist: {mount.source_path}"
                raise StorageVolumeError(msg)
        return list(self._shared_mounts)


__all__ = [
    "NvmeScratchStorageVolumeAdapter",
]
