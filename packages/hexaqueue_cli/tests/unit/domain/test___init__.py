"""Test cli domain exports."""

import hexaqueue_cli.domain


def test_cli_domain_exports() -> None:
    """Verify domain package exports."""
    assert hasattr(hexaqueue_cli.domain, "LocalCliSession")
    assert hasattr(hexaqueue_cli.domain, "parse_run_spec_from_dict")
    assert hasattr(hexaqueue_cli.domain, "parse_run_spec_from_file")
