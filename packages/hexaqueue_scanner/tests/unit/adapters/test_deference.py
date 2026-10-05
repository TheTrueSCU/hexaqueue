"""Unit tests for Provider-Native Deference quarantine adapters."""

from unittest.mock import AsyncMock

import pytest

from hexaqueue_core.domain.collateral import CollateralBundle, CollateralState
from hexaqueue_scanner.adapters.deference import (
    AwsGuardDutyQuarantineAdapter,
    AzureDefenderQuarantineAdapter,
    PassThroughSecurityQuarantineAdapter,
)
from hexaqueue_scanner.domain.config import CloudDeferenceConfig


def _make_sample_bundle(
    bundle_id: str = "b-1", staging_uri: str = "s3://my-bucket/collateral.tar.gz"
) -> CollateralBundle:
    """Helper to create valid CollateralBundle."""
    return CollateralBundle(
        id=bundle_id,
        job_id="job-1",
        filename="collateral.tar.gz",
        size_bytes=1024,
        sha256_checksum="a" * 64,
        staging_uri=staging_uri,
    )


@pytest.mark.asyncio
async def test_aws_guardduty_clean_verdict() -> None:
    """Verify AWS GuardDuty clean tag maps to APPROVED state."""
    fetcher = AsyncMock(return_value={"GuardDutyMalwareScanStatus": "NO_THREATS_FOUND"})
    adapter = AwsGuardDutyQuarantineAdapter(tag_fetcher=fetcher)
    bundle = _make_sample_bundle()

    state, reason = await adapter.scan_collateral(bundle)
    assert state == CollateralState.APPROVED
    assert reason is None
    called = fetcher.called
    assert called is True


@pytest.mark.asyncio
async def test_aws_guardduty_threat_verdict() -> None:
    """Verify AWS GuardDuty threat tag maps to QUARANTINED state."""
    fetcher = AsyncMock(return_value={"GuardDutyMalwareScanStatus": "THREATS_FOUND"})
    adapter = AwsGuardDutyQuarantineAdapter(tag_fetcher=fetcher)
    bundle = _make_sample_bundle()

    state, reason = await adapter.scan_collateral(bundle)
    assert state == CollateralState.QUARANTINED
    assert reason is not None
    has_threat = "threat in collateral.tar.gz" in reason
    assert has_threat is True


@pytest.mark.asyncio
async def test_aws_guardduty_missing_verdict() -> None:
    """Verify missing/pending scan status defaults to QUARANTINED."""
    fetcher = AsyncMock(return_value={})
    adapter = AwsGuardDutyQuarantineAdapter(tag_fetcher=fetcher)
    bundle = _make_sample_bundle()

    state, reason = await adapter.scan_collateral(bundle)
    assert state == CollateralState.QUARANTINED
    assert reason is not None
    has_missing = "verdict missing or pending" in reason
    assert has_missing is True


@pytest.mark.asyncio
async def test_aws_guardduty_tag_fetch_exception() -> None:
    """Verify exception in tag fetcher results in QUARANTINED."""
    fetcher = AsyncMock(side_effect=RuntimeError("S3 AccessDenied"))
    adapter = AwsGuardDutyQuarantineAdapter(tag_fetcher=fetcher)
    bundle = _make_sample_bundle()

    state, reason = await adapter.scan_collateral(bundle)
    assert state == CollateralState.QUARANTINED
    assert reason is not None
    has_err = "Failed to retrieve AWS S3 tags" in reason
    assert has_err is True


@pytest.mark.asyncio
async def test_aws_guardduty_disabled() -> None:
    """Verify disabled GuardDuty config approves immediately."""
    cfg = CloudDeferenceConfig(aws_guardduty_enabled=False)
    adapter = AwsGuardDutyQuarantineAdapter(config=cfg)
    bundle = _make_sample_bundle()

    state, reason = await adapter.scan_collateral(bundle)
    assert state == CollateralState.APPROVED
    assert reason is None


@pytest.mark.asyncio
async def test_azure_defender_clean_verdict() -> None:
    """Verify Azure Defender clean tag maps to APPROVED state."""
    fetcher = AsyncMock(
        return_value={"Malware Scanning scan result": "No threats found"}
    )
    adapter = AzureDefenderQuarantineAdapter(tag_fetcher=fetcher)
    bundle = _make_sample_bundle(
        staging_uri="https://storage.blob.core.windows.net/col"
    )

    state, reason = await adapter.scan_collateral(bundle)
    assert state == CollateralState.APPROVED
    assert reason is None


@pytest.mark.asyncio
async def test_azure_defender_threat_verdict() -> None:
    """Verify Azure Defender threat tag maps to QUARANTINED state."""
    fetcher = AsyncMock(return_value={"Malware Scanning scan result": "Malware found"})
    adapter = AzureDefenderQuarantineAdapter(tag_fetcher=fetcher)
    bundle = _make_sample_bundle(
        staging_uri="https://storage.blob.core.windows.net/col"
    )

    state, reason = await adapter.scan_collateral(bundle)
    assert state == CollateralState.QUARANTINED
    assert reason is not None
    has_threat = "detected malware in collateral.tar.gz" in reason
    assert has_threat is True


@pytest.mark.asyncio
async def test_azure_defender_missing_verdict() -> None:
    """Verify missing Azure Defender tag defaults to QUARANTINED."""
    fetcher = AsyncMock(return_value={})
    adapter = AzureDefenderQuarantineAdapter(tag_fetcher=fetcher)
    bundle = _make_sample_bundle(
        staging_uri="https://storage.blob.core.windows.net/col"
    )

    state, reason = await adapter.scan_collateral(bundle)
    assert state == CollateralState.QUARANTINED
    assert reason is not None
    has_pending = "verdict missing or pending" in reason
    assert has_pending is True


@pytest.mark.asyncio
async def test_azure_defender_tag_fetch_exception() -> None:
    """Verify exception in Azure tag retrieval results in QUARANTINED."""
    fetcher = AsyncMock(side_effect=RuntimeError("BlobStorageError"))
    adapter = AzureDefenderQuarantineAdapter(tag_fetcher=fetcher)
    bundle = _make_sample_bundle()

    state, reason = await adapter.scan_collateral(bundle)
    assert state == CollateralState.QUARANTINED
    assert reason is not None
    has_err = "Failed to retrieve Azure Blob tags" in reason
    assert has_err is True


@pytest.mark.asyncio
async def test_azure_defender_disabled() -> None:
    """Verify disabled Azure Defender config approves immediately."""
    cfg = CloudDeferenceConfig(azure_defender_enabled=False)
    adapter = AzureDefenderQuarantineAdapter(config=cfg)
    bundle = _make_sample_bundle()

    state, reason = await adapter.scan_collateral(bundle)
    assert state == CollateralState.APPROVED
    assert reason is None


@pytest.mark.asyncio
async def test_passthrough_adapter() -> None:
    """Verify PassThroughSecurityQuarantineAdapter approves unconditionally."""
    adapter = PassThroughSecurityQuarantineAdapter()
    bundle = _make_sample_bundle()

    state, reason = await adapter.scan_collateral(bundle)
    assert state == CollateralState.APPROVED
    assert reason is None
