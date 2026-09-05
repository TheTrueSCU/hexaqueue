"""Test domain package exports."""

import data_pipeline.domain


def test_domain_exports() -> None:
    """Verify domain __all__."""
    assert hasattr(data_pipeline.domain, "DataRecord")
    assert hasattr(data_pipeline.domain, "SummaryResult")
