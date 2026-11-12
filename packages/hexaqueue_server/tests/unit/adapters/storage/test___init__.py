"""Unit tests for storage package __init__ exports."""

from hexaqueue_server.adapters.storage import (
    HexaqueueJobModel,
    HexaqueueNodeModel,
    HexaqueueRunModel,
    HexaqueueTelemetryPulseModel,
    InMemorySchedulerStorageAdapter,
    OciAutonomousDatabaseStorageAdapter,
)


def test_storage_package_exports():
    """Verify storage package exports classes cleanly."""
    assert HexaqueueJobModel is not None
    assert HexaqueueNodeModel is not None
    assert HexaqueueRunModel is not None
    assert HexaqueueTelemetryPulseModel is not None
    assert InMemorySchedulerStorageAdapter is not None
    assert OciAutonomousDatabaseStorageAdapter is not None
