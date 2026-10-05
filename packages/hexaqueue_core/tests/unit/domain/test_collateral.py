"""Tests for collateral domain invariants and models."""

import pytest

from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralState,
    CollateralTier,
    can_transition_collateral,
)


def test_collateral_bundle_valid() -> None:
    """Verify valid CollateralBundle creation."""
    bundle = CollateralBundle(
        id="bundle-1",
        job_id="job-1",
        filename="test-bundle.tar.gz",
        kind=CollateralKind.BUNDLE,
        tier=CollateralTier.TEMPORARY,
        sha256_checksum="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        size_bytes=1024,
        staging_uri="file:///tmp/staging/bundle-1",
    )
    assert bundle.id == "bundle-1"
    assert bundle.job_id == "job-1"
    assert bundle.filename == "test-bundle.tar.gz"
    assert bundle.kind == CollateralKind.BUNDLE
    assert bundle.tier == CollateralTier.TEMPORARY
    assert bundle.state == CollateralState.REGISTERED


def test_collateral_bundle_invariants() -> None:
    """Verify CollateralBundle field invariants."""
    with pytest.raises(
        ValueError, match="active_uri can only be set when state is APPROVED"
    ):
        CollateralBundle(
            id="bundle-1",
            job_id="job-1",
            filename="bundle.tar.gz",
            kind=CollateralKind.BUNDLE,
            sha256_checksum="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            size_bytes=1024,
            staging_uri="file:///tmp/staging/bundle-1",
            state=CollateralState.REGISTERED,
            active_uri="file:///tmp/active/bundle-1",
        )

    with pytest.raises(
        ValueError, match="active_uri must be provided when state is APPROVED"
    ):
        CollateralBundle(
            id="bundle-1",
            job_id="job-1",
            filename="bundle.tar.gz",
            kind=CollateralKind.BUNDLE,
            sha256_checksum="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            size_bytes=1024,
            staging_uri="file:///tmp/staging/bundle-1",
            state=CollateralState.APPROVED,
            active_uri=None,
        )

    with pytest.raises(ValueError, match="quarantine_reason must be provided"):
        CollateralBundle(
            id="bundle-1",
            job_id="job-1",
            filename="bundle.tar.gz",
            kind=CollateralKind.BUNDLE,
            sha256_checksum="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            size_bytes=1024,
            staging_uri="file:///tmp/staging/bundle-1",
            state=CollateralState.QUARANTINED,
            quarantine_reason=None,
        )


def test_collateral_transitions() -> None:
    """Verify state transitions."""
    assert (
        can_transition_collateral(CollateralState.REGISTERED, CollateralState.UPLOADED)
        is True
    )
    assert (
        can_transition_collateral(CollateralState.UPLOADED, CollateralState.SCANNING)
        is True
    )
    assert (
        can_transition_collateral(CollateralState.SCANNING, CollateralState.APPROVED)
        is True
    )
    assert (
        can_transition_collateral(CollateralState.SCANNING, CollateralState.QUARANTINED)
        is True
    )
    assert (
        can_transition_collateral(CollateralState.APPROVED, CollateralState.REGISTERED)
        is False
    )
    assert (
        can_transition_collateral(CollateralState.APPROVED, CollateralState.APPROVED)
        is True
    )
