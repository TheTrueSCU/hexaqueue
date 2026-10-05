"""Tests for hexaqueue_server.domain exports."""

from hexaqueue_server import domain


def test_domain_exports() -> None:
    """Verify domain package exports."""
    assert hasattr(domain, "RunStatusReport")
    assert hasattr(domain, "RunSubmission")
