"""Test infra exports."""

import data_pipeline.infra


def test_infra_exports() -> None:
    """Verify infra __all__."""
    assert hasattr(data_pipeline.infra, "load_etl_pipeline")
