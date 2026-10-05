"""Test adapters exports."""

import data_pipeline.adapters


def test_adapters_exports() -> None:
    """Verify adapters __all__."""
    assert hasattr(data_pipeline.adapters, "LocalDataProcessorAdapter")
