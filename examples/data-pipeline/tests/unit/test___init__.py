"""Test root package exports."""

import data_pipeline


def test_package_exports() -> None:
    """Verify package __all__."""
    assert hasattr(data_pipeline, "DataRecord")
    assert hasattr(data_pipeline, "SummaryResult")
    assert hasattr(data_pipeline, "DataProcessorPort")
    assert hasattr(data_pipeline, "LocalDataProcessorAdapter")
    assert hasattr(data_pipeline, "load_etl_pipeline")
