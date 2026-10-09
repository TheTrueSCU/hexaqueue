"""Unit tests for JobRetryPolicy and DeadLetterRecord domain entities."""

from datetime import UTC, datetime

import pytest

from hexaqueue_core.domain.retry import DeadLetterRecord, JobRetryPolicy


def test_job_retry_policy_defaults_and_backoff_calculation() -> None:
    """Verify default backoff exponential curve computation."""
    policy = JobRetryPolicy()

    # Attempt 0 or negative
    zero_delay = policy.compute_backoff_seconds(0)
    assert zero_delay == 0.0

    # Attempt 1: initial_backoff * (factor ** 0) = 1.0 * 1 = 1.0
    delay_1 = policy.compute_backoff_seconds(1)
    assert delay_1 == 1.0

    # Attempt 2: 1.0 * (2.0 ** 1) = 2.0
    delay_2 = policy.compute_backoff_seconds(2)
    assert delay_2 == 2.0

    # Attempt 3: 1.0 * (2.0 ** 2) = 4.0
    delay_3 = policy.compute_backoff_seconds(3)
    assert delay_3 == 4.0

    # Large attempt is capped at max_backoff_seconds
    capped_delay = policy.compute_backoff_seconds(10)
    assert capped_delay == 60.0


def test_job_retry_policy_invalid_bounds() -> None:
    """Verify error when initial_backoff_seconds exceeds max_backoff_seconds."""
    with pytest.raises(ValueError, match="cannot exceed max_backoff_seconds"):
        JobRetryPolicy(initial_backoff_seconds=100.0, max_backoff_seconds=10.0)


def test_dead_letter_record_creation_and_validation() -> None:
    """Verify dead-letter record fields and invariant validation."""
    now = datetime.now(UTC)
    record = DeadLetterRecord(
        job_id="job-123",
        run_id="run-456",
        failure_reason="Process crashed with SIGSEGV",
        retry_count=3,
        last_worker_id="worker-node-1",
        diagnostics={"exit_code": "-11", "host": "srv-1"},
        timestamp=now,
    )

    j_id = record.job_id
    r_id = record.run_id
    reason = record.failure_reason
    retries = record.retry_count
    worker = record.last_worker_id
    diag = record.diagnostics
    ts = record.timestamp

    assert j_id == "job-123"
    assert r_id == "run-456"
    assert reason == "Process crashed with SIGSEGV"
    assert retries == 3
    assert worker == "worker-node-1"
    assert diag["exit_code"] == "-11"
    assert ts == now


@pytest.mark.parametrize(
    ("job_id", "run_id", "reason"),
    [
        ("", "run-1", "failure"),
        ("job-1", "", "failure"),
        ("job-1", "run-1", "   "),
    ],
)
def test_dead_letter_record_invalid_identifiers(
    job_id: str, run_id: str, reason: str
) -> None:
    """Verify validation errors on blank identifiers."""
    with pytest.raises(ValueError, match="cannot be empty"):
        DeadLetterRecord(
            job_id=job_id,
            run_id=run_id,
            failure_reason=reason,
            retry_count=1,
        )
