"""Unit tests for collateral domain models."""

import pytest
from hexaqueue_collateral.domain.models import IngestionRequest, StagedUploadDescriptor
from hexaqueue_core.domain.collateral import CollateralBundle


def test_ingestion_request_valid():
    """Verify IngestionRequest validates fields properly."""
    req = IngestionRequest(
        job_id="job-1",
        filename="model.bin",
        size_bytes=1024,
        sha256_checksum="a" * 64,
    )
    assert req.job_id == "job-1"
    assert req.filename == "model.bin"
    assert req.size_bytes == 1024


def test_ingestion_request_invalid():
    """Verify IngestionRequest rejects empty job_id or filename."""
    with pytest.raises(ValueError, match="job_id cannot be empty"):
        IngestionRequest(
            job_id="",
            filename="model.bin",
            size_bytes=100,
            sha256_checksum="a" * 64,
        )

    with pytest.raises(ValueError, match="filename cannot be empty"):
        IngestionRequest(
            job_id="job-1",
            filename="  ",
            size_bytes=100,
            sha256_checksum="a" * 64,
        )


def test_staged_upload_descriptor():
    """Verify StagedUploadDescriptor holds bundle and upload destination."""
    bundle = CollateralBundle(
        id="col-1",
        job_id="job-1",
        filename="test.bin",
        size_bytes=512,
        sha256_checksum="b" * 64,
        staging_uri="/tmp/staging/test.bin",
    )
    desc = StagedUploadDescriptor(
        bundle=bundle,
        upload_url="file:///tmp/staging/test.bin",
        staging_path="/tmp/staging/test.bin",
    )
    assert desc.bundle.id == "col-1"
    assert desc.upload_url.startswith("file://")
