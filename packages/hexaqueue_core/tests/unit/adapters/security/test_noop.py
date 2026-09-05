"""Unit tests for no-op security quarantine adapter."""

import pytest
from hexaqueue_core.adapters.security.noop import NoOpSecurityQuarantineAdapter
from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralState,
    CollateralTier,
)


@pytest.mark.asyncio
async def test_noop_security_quarantine():
    """Verify no-op security quarantine approves collateral."""
    scanner = NoOpSecurityQuarantineAdapter()
    bundle = CollateralBundle(
        id="c1",
        job_id="j1",
        filename="data.csv",
        size_bytes=100,
        sha256_checksum="a" * 64,
        kind=CollateralKind.BUNDLE,
        tier=CollateralTier.TEMPORARY,
        state=CollateralState.UPLOADED,
        staging_uri="/tmp/staging/data.csv",
    )
    state, reason = await scanner.scan_collateral(bundle)
    assert state == CollateralState.APPROVED
    assert reason is None
