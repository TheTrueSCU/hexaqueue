"""Test cli package exports."""

import hexaqueue_cli


def test_cli_package_exports() -> None:
    """Verify package exports."""
    assert hasattr(hexaqueue_cli, "LocalClientAdapter")
    assert hasattr(hexaqueue_cli, "LocalCliSession")
    assert hasattr(hexaqueue_cli, "CliBootstrapper")
    assert hasattr(hexaqueue_cli, "ClientPort")
    assert hasattr(hexaqueue_cli, "parse_run_spec_from_dict")
    assert hasattr(hexaqueue_cli, "parse_run_spec_from_file")
