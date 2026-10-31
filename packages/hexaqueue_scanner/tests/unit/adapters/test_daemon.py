"""Unit tests for scanner daemon worker adapter."""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralState,
    CollateralTier,
)
from hexaqueue_core.ports.security import SecurityScanResult
from hexaqueue_scanner.adapters.composite import CompositeQuarantineScannerAdapter
from hexaqueue_scanner.adapters.daemon import ScannerDaemonAdapter
from hexaqueue_scanner.adapters.queue import InMemoryScanTaskQueueAdapter
from hexaqueue_scanner.domain.config import ScannerConfig
from hexaqueue_scanner.domain.events import (
    CollateralApprovedEvent,
    CollateralQuarantinedEvent,
    CollateralRejectedEvent,
    SecurityScanCompletedEvent,
)
from hexaqueue_scanner.ports.engine import MalwareScannerEnginePort


class MockEngine(MalwareScannerEnginePort):
    """Mock scanner engine for testing."""

    def __init__(self, is_clean: bool = True, threat_name: str | None = None) -> None:
        self.is_clean = is_clean
        self.threat_name = threat_name

    async def scan_file(self, file_path: Path) -> SecurityScanResult:
        """Return preset scan result."""
        return SecurityScanResult(
            is_clean=self.is_clean,
            threat_name=self.threat_name,
            scanner_engine="MockEngine",
        )

    async def ping(self) -> bool:
        """Always healthy."""
        return True


@pytest.fixture
def temp_bundle_file(tmp_path: Path) -> tuple[Path, CollateralBundle]:
    """Create a temporary collateral bundle and on-disk payload."""
    payload = tmp_path / "bundle.tar"
    payload.write_bytes(b"mock safe bundle content")
    bundle = CollateralBundle(
        id="col-test-01",
        job_id="job-100",
        filename="bundle.tar",
        size_bytes=len(b"mock safe bundle content"),
        sha256_checksum="abc" * 21 + "a",
        kind=CollateralKind.BUNDLE,
        tier=CollateralTier.TEMPORARY,
        state=CollateralState.UPLOADED,
        staging_uri=str(payload),
    )
    return payload, bundle


@pytest.mark.asyncio
async def test_daemon_process_clean_bundle(
    temp_bundle_file: tuple[Path, CollateralBundle],
) -> None:
    """Verify clean scan outcome results in approval and metrics increment."""
    _, bundle = temp_bundle_file
    engine = MockEngine(is_clean=True)
    composite = CompositeQuarantineScannerAdapter(engines=[engine])
    queue = InMemoryScanTaskQueueAdapter()

    collateral_service = AsyncMock()
    collateral_service.get_bundle.return_value = bundle
    approved_bundle = bundle.model_copy(
        update={
            "state": CollateralState.APPROVED,
            "active_uri": "/cas/active/bundle.tar",
        }
    )
    collateral_service.process_quarantine.return_value = approved_bundle

    events: list[Any] = []
    daemon = ScannerDaemonAdapter(
        composite_scanner=composite,
        task_queue=queue,
        collateral_service=collateral_service,
        event_handlers=[events.append],
    )

    report = await daemon.process_bundle(bundle.id)
    is_clean = report.is_clean
    assert is_clean is True

    metrics = daemon.get_metrics()
    total = metrics.total_scans
    assert total == 1
    approved = metrics.approved_scans
    assert approved == 1
    quarantined = metrics.quarantined_scans
    assert quarantined == 0

    assert len(events) == 2
    approved_event = next(e for e in events if isinstance(e, CollateralApprovedEvent))
    cid = approved_event.collateral_id
    assert cid == bundle.id

    completed_event = next(
        e for e in events if isinstance(e, SecurityScanCompletedEvent)
    )
    st = completed_event.state
    assert st == CollateralState.APPROVED


@pytest.mark.asyncio
async def test_daemon_process_threat_bundle(
    temp_bundle_file: tuple[Path, CollateralBundle],
) -> None:
    """Verify threat detection results in quarantine isolation and event emission."""
    _, bundle = temp_bundle_file
    engine = MockEngine(is_clean=False, threat_name="Trojan.Dropper.Generic")
    composite = CompositeQuarantineScannerAdapter(
        engines=[engine], config=ScannerConfig(quarantine_on_threat=True)
    )
    queue = InMemoryScanTaskQueueAdapter()

    collateral_service = AsyncMock()
    collateral_service.get_bundle.return_value = bundle
    quarantined_bundle = bundle.model_copy(
        update={
            "state": CollateralState.QUARANTINED,
            "staging_uri": "/vault/quarantine/bad.tar",
        }
    )
    collateral_service.process_quarantine.return_value = quarantined_bundle

    events: list[Any] = []
    daemon = ScannerDaemonAdapter(
        composite_scanner=composite,
        task_queue=queue,
        collateral_service=collateral_service,
        event_handlers=[events.append],
    )

    report = await daemon.process_bundle(bundle.id)
    is_clean = report.is_clean
    assert is_clean is False

    metrics = daemon.get_metrics()
    total = metrics.total_scans
    assert total == 1
    quarantined = metrics.quarantined_scans
    assert quarantined == 1

    quarantined_event = next(
        e for e in events if isinstance(e, CollateralQuarantinedEvent)
    )
    threat = quarantined_event.threat_name
    assert threat == "Trojan.Dropper.Generic"


@pytest.mark.asyncio
async def test_daemon_process_missing_file_rejected(
    temp_bundle_file: tuple[Path, CollateralBundle],
) -> None:
    """Verify missing file yields REJECTED event and incremented rejection metric."""
    payload_path, bundle = temp_bundle_file
    payload_path.unlink()  # File no longer exists

    engine = MockEngine(is_clean=True)
    composite = CompositeQuarantineScannerAdapter(engines=[engine])
    queue = InMemoryScanTaskQueueAdapter()

    collateral_service = AsyncMock()
    collateral_service.get_bundle.return_value = bundle

    events: list[Any] = []
    daemon = ScannerDaemonAdapter(
        composite_scanner=composite,
        task_queue=queue,
        collateral_service=collateral_service,
        event_handlers=[events.append],
    )

    report = await daemon.process_bundle(bundle.id)
    is_clean = report.is_clean
    assert is_clean is False

    metrics = daemon.get_metrics()
    rejected = metrics.rejected_scans
    assert rejected == 1

    rejected_event = next(e for e in events if isinstance(e, CollateralRejectedEvent))
    reason = rejected_event.reason
    assert "missing" in reason.lower()


@pytest.mark.asyncio
async def test_daemon_standalone_fallback() -> None:
    """Verify daemon behavior when collateral_service is not configured."""
    engine = MockEngine(is_clean=True)
    composite = CompositeQuarantineScannerAdapter(engines=[engine])
    queue = InMemoryScanTaskQueueAdapter()

    daemon = ScannerDaemonAdapter(
        composite_scanner=composite,
        task_queue=queue,
        collateral_service=None,
    )
    report = await daemon.process_bundle("col-orphan")
    is_clean = report.is_clean
    assert is_clean is False

    metrics = daemon.get_metrics()
    errors = metrics.error_scans
    assert errors == 1


@pytest.mark.asyncio
async def test_daemon_start_stop_worker_loop(
    temp_bundle_file: tuple[Path, CollateralBundle],
) -> None:
    """Verify background queue polling lifecycle."""
    _, bundle = temp_bundle_file
    engine = MockEngine(is_clean=True)
    composite = CompositeQuarantineScannerAdapter(engines=[engine])
    queue = InMemoryScanTaskQueueAdapter()

    collateral_service = AsyncMock()
    collateral_service.get_bundle.return_value = bundle
    collateral_service.process_quarantine.return_value = bundle.model_copy(
        update={"state": CollateralState.APPROVED}
    )

    daemon = ScannerDaemonAdapter(
        composite_scanner=composite,
        task_queue=queue,
        collateral_service=collateral_service,
        poll_interval_seconds=0.01,
    )

    running_init = daemon.is_running()
    assert running_init is False

    await daemon.start()
    running_started = daemon.is_running()
    assert running_started is True

    # Starting again should be a no-op
    await daemon.start()

    # Enqueue a task to be processed by background loop
    await queue.enqueue_task(bundle.id)

    # Allow worker loop to pick up and process
    await asyncio.sleep(0.08)

    metrics = daemon.get_metrics()
    total = metrics.total_scans
    assert total >= 1

    await daemon.stop()
    running_stopped = daemon.is_running()
    assert running_stopped is False
