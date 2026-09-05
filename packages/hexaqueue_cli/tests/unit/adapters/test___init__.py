"""Test cli adapters exports."""

import hexaqueue_cli.adapters


def test_cli_adapters_exports() -> None:
    """Verify adapters package exports."""
    assert hasattr(hexaqueue_cli.adapters, "LocalClientAdapter")
