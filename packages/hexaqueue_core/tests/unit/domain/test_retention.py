"""Unit tests for storage retention domain models and policies.

Notes/Architectural Intent:
    Tests differential retention resolution across terminal execution outcomes.
"""

import pytest
from pydantic import ValidationError

from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.retention import LogRetentionPolicy, LogRetentionTier


def test_retention_tier_values() -> None:
    """Validate enumeration values for log retention tiers."""
    short_val = LogRetentionTier.SHORT_PASS.value
    long_val = LogRetentionTier.LONG_FAIL.value
    assert short_val == "SHORT_PASS"
    assert long_val == "LONG_FAIL"


def test_retention_policy_for_completed_outcome() -> None:
    """Verify COMPLETED jobs resolve to SHORT_PASS 14-day retention."""
    policy = LogRetentionPolicy.for_outcome(TerminalOutcome.COMPLETED)
    assert policy.tier == LogRetentionTier.SHORT_PASS
    assert policy.ttl_days == 14
    assert policy.tag_key == "Retention"
    assert policy.tag_value == "ShortPass"


@pytest.mark.parametrize(
    "outcome",
    [
        TerminalOutcome.FAILED,
        TerminalOutcome.TIMED_OUT,
        TerminalOutcome.CANCELLED,
        TerminalOutcome.PREEMPTED,
    ],
)
def test_retention_policy_for_failed_outcomes(outcome: TerminalOutcome) -> None:
    """Verify non-success terminal outcomes resolve to LONG_FAIL 90-day retention."""
    policy = LogRetentionPolicy.for_outcome(outcome)
    assert policy.tier == LogRetentionTier.LONG_FAIL
    assert policy.ttl_days == 90
    assert policy.tag_key == "Retention"
    assert policy.tag_value == "LongFail"


def test_retention_policy_immutability() -> None:
    """Verify LogRetentionPolicy is immutable."""
    policy = LogRetentionPolicy.for_outcome(TerminalOutcome.COMPLETED)
    with pytest.raises(ValidationError):
        setattr(policy, "ttl_days", 30)  # noqa: B010
