"""Tests for Hexaqueue domain exceptions."""

import pytest

from hexaqueue_core.domain.exceptions import (
    ChecksumMismatchError,
    FreeTierLimitExceededError,
    HexaqueueConfigError,
    HexaqueueError,
    JobStateTransitionError,
    QuotaExceededError,
)


def test_exception_hierarchy() -> None:
    """Verify all custom exceptions inherit from HexaqueueError."""
    assert issubclass(HexaqueueConfigError, HexaqueueError)
    assert issubclass(FreeTierLimitExceededError, HexaqueueError)
    assert issubclass(ChecksumMismatchError, HexaqueueError)
    assert issubclass(QuotaExceededError, HexaqueueError)
    assert issubclass(JobStateTransitionError, HexaqueueError)

    with pytest.raises(HexaqueueError):
        raise ChecksumMismatchError("Checksum mismatch")
