"""Local filesystem scratch storage adapter."""

from hexaqueue_core.adapters.storage.in_memory import InMemoryStorageVolumeAdapter

LocalDiskStorageVolumeAdapter = InMemoryStorageVolumeAdapter

__all__ = [
    "LocalDiskStorageVolumeAdapter",
]
