"""Unit tests for storage package __init__ exports."""

from hexaqueue_server.adapters.storage import (
    DatabaseLeaderElectionAdapter,
    HexaqueueJobModel,
    HexaqueueLeaderLeaseModel,
    HexaqueueNodeModel,
    HexaqueueRunModel,
    HexaqueueTelemetryPulseModel,
    InMemorySchedulerStorageAdapter,
    OciAutonomousDatabaseStorageAdapter,
)


def test_storage_package_exports() -> None:
    """Verify storage package exports classes cleanly."""
    assert DatabaseLeaderElectionAdapter is not None
    assert HexaqueueJobModel is not None
    assert HexaqueueLeaderLeaseModel is not None
    assert HexaqueueNodeModel is not None
    assert HexaqueueRunModel is not None
    assert HexaqueueTelemetryPulseModel is not None
    assert InMemorySchedulerStorageAdapter is not None
    assert OciAutonomousDatabaseStorageAdapter is not None
