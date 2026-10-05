"""Test cli ports exports."""

import hexaqueue_cli.ports


def test_cli_ports_exports() -> None:
    """Verify ports package exports."""
    assert hasattr(hexaqueue_cli.ports, "ClientPort")
