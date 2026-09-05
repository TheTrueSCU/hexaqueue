"""Test commands exports."""

import hexaqueue_cli.commands


def test_commands_exports() -> None:
    """Verify commands package exports."""
    assert hasattr(hexaqueue_cli.commands, "run_app")
