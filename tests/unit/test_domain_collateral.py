"""Unit tests for Collateral domain models, state transitions, and invariants."""

import pytest

from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralState,
    CollateralTier,
    can_transition_collateral,
)


def test_valid_collateral_transitions():
    """Verify legal state transitions in the quarantine pipeline."""
    assert can_transition_collateral(
        CollateralState.REGISTERED, CollateralState.UPLOADED
    )
    assert can_transition_collateral(CollateralState.UPLOADED, CollateralState.SCANNING)
    assert can_transition_collateral(CollateralState.SCANNING, CollateralState.APPROVED)
    assert can_transition_collateral(
        CollateralState.SCANNING, CollateralState.QUARANTINED
    )
    assert can_transition_collateral(CollateralState.SCANNING, CollateralState.REJECTED)
    assert can_transition_collateral(
        CollateralState.REGISTERED, CollateralState.REJECTED
    )


def test_invalid_collateral_transitions():
    """Verify illegal jumps in the quarantine pipeline are disallowed."""
    assert not can_transition_collateral(
        CollateralState.REGISTERED, CollateralState.APPROVED
    )
    assert not can_transition_collateral(
        CollateralState.UPLOADED, CollateralState.APPROVED
    )
    assert not can_transition_collateral(
        CollateralState.APPROVED, CollateralState.SCANNING
    )
    assert not can_transition_collateral(
        CollateralState.QUARANTINED, CollateralState.APPROVED
    )


def test_collateral_bundle_approved_invariant():
    """Verify active_uri is required when APPROVED and forbidden when unapproved."""
    valid_sha = "a" * 64

    # APPROVED requires active_uri
    with pytest.raises(
        ValueError, match="active_uri must be provided when state is APPROVED"
    ):
        CollateralBundle(
            id="c1",
            job_id="j1",
            filename="test.bin",
            size_bytes=1024,
            sha256_checksum=valid_sha,
            state=CollateralState.APPROVED,
            staging_uri="s3://staging/c1/test.bin",
            active_uri=None,
        )

    # REGISTERED cannot have active_uri
    with pytest.raises(
        ValueError, match="active_uri can only be set when state is APPROVED"
    ):
        CollateralBundle(
            id="c1",
            job_id="j1",
            filename="test.bin",
            size_bytes=1024,
            sha256_checksum=valid_sha,
            state=CollateralState.REGISTERED,
            staging_uri="s3://staging/c1/test.bin",
            active_uri="s3://active/test.bin",
        )


def test_collateral_bundle_quarantine_reason_invariant():
    """Verify quarantine_reason is mandatory when QUARANTINED or REJECTED."""
    valid_sha = "b" * 64

    with pytest.raises(
        ValueError, match="quarantine_reason must be provided when state is QUARANTINED"
    ):
        CollateralBundle(
            id="c1",
            job_id="j1",
            filename="malware.bin",
            size_bytes=2048,
            sha256_checksum=valid_sha,
            state=CollateralState.QUARANTINED,
            staging_uri="s3://staging/c1/malware.bin",
            quarantine_reason=None,
        )

    with pytest.raises(
        ValueError, match="quarantine_reason must be provided when state is REJECTED"
    ):
        CollateralBundle(
            id="c1",
            job_id="j1",
            filename="corrupt.bin",
            size_bytes=2048,
            sha256_checksum=valid_sha,
            state=CollateralState.REJECTED,
            staging_uri="s3://staging/c1/corrupt.bin",
            quarantine_reason="",
        )


def test_collateral_valid_creation():
    """Verify valid creation of approved and registered bundles."""
    valid_sha = "c" * 64

    bundle = CollateralBundle(
        id="c1",
        job_id="j1",
        filename="model.onnx",
        size_bytes=1048576,
        sha256_checksum=valid_sha,
        kind=CollateralKind.DATASET,
        tier=CollateralTier.PERMANENT,
        state=CollateralState.APPROVED,
        staging_uri="s3://staging/c1/model.onnx",
        active_uri="s3://clean/models/model.onnx",
        active_pin_count=2,
    )

    assert bundle.kind == CollateralKind.DATASET
    assert bundle.tier == CollateralTier.PERMANENT
    assert bundle.state == CollateralState.APPROVED
    assert bundle.active_pin_count == 2
