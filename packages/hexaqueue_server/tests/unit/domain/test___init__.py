"""Tests for hexaqueue_server.domain exports."""

from hexaqueue_server import domain


def test_domain_exports() -> None:
    """Verify domain package exports."""
    has_autoscaler = hasattr(domain, "BudgetAwareInstancePoolAutoscaler")
    has_mode = hasattr(domain, "BudgetStrategyMode")
    has_policy = hasattr(domain, "CreditPacingPolicy")
    has_report = hasattr(domain, "RunStatusReport")
    has_submission = hasattr(domain, "RunSubmission")
    assert has_autoscaler is True
    assert has_mode is True
    assert has_policy is True
    assert has_report is True
    assert has_submission is True
