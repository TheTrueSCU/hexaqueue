"""In-memory scratch storage adapter."""

import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from hexaqueue_core.ports.storage import StorageVolumePort, VolumeAllocation


class InMemoryStorageVolumeAdapter(StorageVolumePort):
    """In-memory / ephemeral temporary scratch directory storage adapter."""

    def __init__(self, base_scratch_dir: str | None = None) -> None:
        self._base_dir = (
            Path(base_scratch_dir)
            if base_scratch_dir
            else Path(tempfile.gettempdir()) / "hexaqueue_scratch"
        )
        self._allocations: dict[str, Path] = {}

    async def allocate_scratch(
        self, job_id: str, size_mb: int, base_dir: str | None = None
    ) -> VolumeAllocation:
        """Create an ephemeral temporary directory for job execution."""
        root = Path(base_dir) if base_dir else self._base_dir
        root.mkdir(parents=True, exist_ok=True)
        mount_path = Path(tempfile.mkdtemp(prefix=f"hq-scratch-{job_id}-", dir=root))
        volume_id = f"vol-{uuid4().hex[:8]}"
        self._allocations[volume_id] = mount_path
        return VolumeAllocation(
            volume_id=volume_id,
            mount_path=str(mount_path),
            size_mb=size_mb,
            is_ephemeral=True,
        )

    async def cleanup_scratch(self, volume_id: str) -> None:
        """Remove temporary directory."""
        if volume_id in self._allocations:
            path = self._allocations.pop(volume_id)
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)


__all__ = [
    "InMemoryStorageVolumeAdapter",
]
