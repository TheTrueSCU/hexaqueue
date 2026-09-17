"""Test cli infra exports."""

import hexaqueue_cli.infra


def test_cli_infra_exports() -> None:
    """Verify infra package exports."""
    assert hasattr(hexaqueue_cli.infra, "CliBootstrapper")
    assert hasattr(hexaqueue_cli.infra, "format_option")
    assert hasattr(hexaqueue_cli.infra, "resolve_format")
