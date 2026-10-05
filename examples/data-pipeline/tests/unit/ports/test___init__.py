"""Test ports exports."""

import data_pipeline.ports


def test_ports_exports() -> None:
    """Verify ports __all__."""
    assert hasattr(data_pipeline.ports, "DataProcessorPort")
