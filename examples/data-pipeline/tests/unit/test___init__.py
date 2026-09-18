"""Test root package exports."""

import data_pipeline


def test_package_exports() -> None:
    """Verify package __all__."""
    has_record = hasattr(data_pipeline, "DataRecord")
    assert has_record is True
    has_summary = hasattr(data_pipeline, "SummaryResult")
    assert has_summary is True
    has_port = hasattr(data_pipeline, "DataProcessorPort")
    assert has_port is True
    has_adapter = hasattr(data_pipeline, "LocalDataProcessorAdapter")
    assert has_adapter is True
    has_runner = hasattr(data_pipeline, "load_etl_pipeline")
    assert has_runner is True
