"""Unit tests for CollateralGcRunner background daemon."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from hexaqueue_collateral.infra.gc import CollateralGcRunner
from hexaqueue_collateral.ports.service import CollateralServicePort


@pytest.mark.asyncio
async def test_gc_runner_lifecycle():
    """Verify start and stop lifecycle for CollateralGcRunner."""
    mock_service = AsyncMock(spec=CollateralServicePort)
    runner = CollateralGcRunner(service=mock_service, interval_seconds=0.05)

    is_running_init = runner.is_running
    assert is_running_init is False

    started = await runner.start()
    assert started is runner

    # Starting twice is idempotent
    started_again = await runner.start()
    assert started_again is runner

    is_running_started = runner.is_running
    assert is_running_started is True

    await runner.stop()
    is_running_stopped = runner.is_running
    assert is_running_stopped is False

    # Stopping twice is idempotent
    await runner.stop()
    is_running_stopped_again = runner.is_running
    assert is_running_stopped_again is False


@pytest.mark.asyncio
async def test_gc_runner_run_once():
    """Verify single sweep execution passes configured thresholds to service."""
    mock_service = AsyncMock(spec=CollateralServicePort)
    mock_service.evict_expired.return_value = ["col-1", "col-2"]

    runner = CollateralGcRunner(
        service=mock_service,
        interval_seconds=60.0,
        max_age_seconds=3600,
        high_watermark_bytes=1000000,
    )

    evicted = await runner.run_once()
    assert evicted == ["col-1", "col-2"]
    mock_service.evict_expired.assert_awaited_once_with(
        max_age_seconds=3600,
        high_watermark_bytes=1000000,
    )


@pytest.mark.asyncio
async def test_gc_runner_handles_exceptions():
    """Verify run_once catches exceptions gracefully and returns empty list."""
    mock_service = AsyncMock(spec=CollateralServicePort)
    mock_service.evict_expired.side_effect = RuntimeError("Storage failure")

    runner = CollateralGcRunner(service=mock_service)
    evicted = await runner.run_once()
    assert evicted == []


@pytest.mark.asyncio
async def test_gc_runner_background_loop():
    """Verify background loop triggers periodic evictions."""
    mock_service = AsyncMock(spec=CollateralServicePort)
    mock_service.evict_expired.return_value = ["col-auto"]

    runner = CollateralGcRunner(service=mock_service, interval_seconds=0.01)
    await runner.start()
    await asyncio.sleep(0.035)
    await runner.stop()

    call_count = mock_service.evict_expired.await_count
    assert call_count >= 1
