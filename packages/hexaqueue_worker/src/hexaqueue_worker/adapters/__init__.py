"""Adapters package for hexaqueue-worker."""

from hexaqueue_worker.adapters.apptainer import ApptainerExecutionRuntimeAdapter
from hexaqueue_worker.adapters.cgroups import CgroupsV2ProcessAdapter
from hexaqueue_worker.adapters.deference import NativeDeferenceRuntimeAdapter
from hexaqueue_worker.adapters.gpu import (
    MockGpuDeviceManagerAdapter,
    NvmlGpuDeviceManagerAdapter,
)
from hexaqueue_worker.adapters.local import LocalSubprocessWorker
from hexaqueue_worker.adapters.podman import PodmanExecutionRuntimeAdapter
from hexaqueue_worker.adapters.pty import LocalPtyBridgeAdapter
from hexaqueue_worker.adapters.storage import NvmeScratchStorageVolumeAdapter
from hexaqueue_worker.adapters.telemetry import LocalTelemetryCollector

__all__ = [
    "ApptainerExecutionRuntimeAdapter",
    "CgroupsV2ProcessAdapter",
    "LocalPtyBridgeAdapter",
    "LocalSubprocessWorker",
    "LocalTelemetryCollector",
    "MockGpuDeviceManagerAdapter",
    "NativeDeferenceRuntimeAdapter",
    "NvmeScratchStorageVolumeAdapter",
    "NvmlGpuDeviceManagerAdapter",
    "PodmanExecutionRuntimeAdapter",
]
