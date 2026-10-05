"""Unit tests for NotificationTrigger flags, NotificationPolicy, and lifecycle mapping."""

from typing import Any

import pytest
from hexastack_core.ports.notification import NotificationPriority

from hexaqueue_core.domain.lifecycle import (
    JobState,
    RunOutcome,
    RunState,
    TerminalOutcome,
)
from hexaqueue_core.domain.notification import (
    NotificationPolicy,
    NotificationTrigger,
    map_lifecycle_to_trigger,
)


def test_notification_trigger_bitwise_combinations() -> None:
    """Verify bitwise flags combine and match expected trigger subsets."""
    combo = (
        NotificationTrigger.COMPLETED
        | NotificationTrigger.FAILED
        | NotificationTrigger.PREEMPTED
    )

    res_comp = combo.matches(NotificationTrigger.COMPLETED)
    assert res_comp is True

    res_fail = combo.matches(NotificationTrigger.FAILED)
    assert res_fail is True

    res_preempt = combo.matches(NotificationTrigger.PREEMPTED)
    assert res_preempt is True

    res_started = combo.matches(NotificationTrigger.STARTED)
    assert res_started is False

    # Check composite aliases
    res_err_fail = NotificationTrigger.ERRORS.matches(NotificationTrigger.FAILED)
    assert res_err_fail is True

    res_err_timed = NotificationTrigger.ERRORS.matches(NotificationTrigger.TIMED_OUT)
    assert res_err_timed is True

    res_term_comp = NotificationTrigger.TERMINAL.matches(NotificationTrigger.COMPLETED)
    assert res_term_comp is True

    res_all_sub = NotificationTrigger.ALL.matches(NotificationTrigger.SUBMITTED)
    assert res_all_sub is True


def test_notification_trigger_parse() -> None:
    """Verify NotificationTrigger parsing across strings, lists, bitmasks, and invalid inputs."""
    # Comma-separated string
    t1 = NotificationTrigger.parse("COMPLETED, FAILED")
    res1_comp = t1.matches(NotificationTrigger.COMPLETED)
    res1_fail = t1.matches(NotificationTrigger.FAILED)
    assert res1_comp is True
    assert res1_fail is True

    # Pipe-separated string
    t2 = NotificationTrigger.parse("STARTED | CANCELLED")
    res2_start = t2.matches(NotificationTrigger.STARTED)
    res2_canc = t2.matches(NotificationTrigger.CANCELLED)
    assert res2_start is True
    assert res2_canc is True

    # Composite alias string
    t3 = NotificationTrigger.parse("ERRORS")
    res3 = t3 == NotificationTrigger.ERRORS
    assert res3 is True

    # List of strings
    t4 = NotificationTrigger.parse(["STARTED", "COMPLETED"])
    res4 = t4 == (NotificationTrigger.STARTED | NotificationTrigger.COMPLETED)
    assert res4 is True

    # Integer bitmask
    bitmask = int(NotificationTrigger.FAILED | NotificationTrigger.TIMED_OUT)
    t5 = NotificationTrigger.parse(bitmask)
    res5 = t5.matches(NotificationTrigger.FAILED)
    assert res5 is True

    # Passthrough existing instance
    t6 = NotificationTrigger.parse(NotificationTrigger.PREEMPTED)
    assert t6 == NotificationTrigger.PREEMPTED

    # Empty string returns NONE
    t7 = NotificationTrigger.parse("   ")
    assert t7 == NotificationTrigger.NONE

    # Numeric string
    t8 = NotificationTrigger.parse(str(bitmask))
    assert t8 == t5

    # Invalid string raises ValueError
    with pytest.raises(ValueError, match="Unknown notification trigger 'BOGUS'"):
        NotificationTrigger.parse("COMPLETED, BOGUS")

    # Invalid type raises ValueError
    bad_val: Any = object()
    with pytest.raises(ValueError, match="Cannot parse NotificationTrigger from type"):
        NotificationTrigger.parse(bad_val)


def test_notification_policy_model() -> None:
    """Verify NotificationPolicy instantiation, validation, and trigger coercion."""
    policy = NotificationPolicy(
        targets=[" slack://webhook ", "mailto://ops@domain.com "],
        triggers="COMPLETED,FAILED",
        priority=NotificationPriority.HIGH,
        tags=["cluster-a"],
    )

    # Targets stripped
    assert policy.targets == ["slack://webhook", "mailto://ops@domain.com"]

    # Triggers coerced to NotificationTrigger
    res_comp = policy.triggers.matches(NotificationTrigger.COMPLETED)
    res_fail = policy.triggers.matches(NotificationTrigger.FAILED)
    res_start = policy.triggers.matches(NotificationTrigger.STARTED)
    assert res_comp is True
    assert res_fail is True
    assert res_start is False

    assert policy.priority == NotificationPriority.HIGH
    assert policy.escalate_on_error is True
    assert policy.tags == ["cluster-a"]


def test_map_lifecycle_to_trigger_for_job() -> None:
    """Verify JobState and TerminalOutcome map correctly to NotificationTriggers."""
    t_sub = map_lifecycle_to_trigger(JobState.SUBMITTED)
    assert t_sub == NotificationTrigger.SUBMITTED

    t_run = map_lifecycle_to_trigger(JobState.RUNNING)
    assert t_run == NotificationTrigger.STARTED

    t_comp = map_lifecycle_to_trigger(JobState.DONE, TerminalOutcome.COMPLETED)
    assert t_comp == NotificationTrigger.COMPLETED

    t_fail = map_lifecycle_to_trigger(JobState.DONE, TerminalOutcome.FAILED)
    assert t_fail == NotificationTrigger.FAILED

    t_canc = map_lifecycle_to_trigger(JobState.DONE, TerminalOutcome.CANCELLED)
    assert t_canc == NotificationTrigger.CANCELLED

    t_time = map_lifecycle_to_trigger(JobState.DONE, TerminalOutcome.TIMED_OUT)
    assert t_time == NotificationTrigger.TIMED_OUT

    t_preempt = map_lifecycle_to_trigger(JobState.DONE, TerminalOutcome.PREEMPTED)
    assert t_preempt == NotificationTrigger.PREEMPTED

    # Unmonitored intermediate states return None
    t_pend = map_lifecycle_to_trigger(JobState.PENDING)
    assert t_pend is None

    t_block = map_lifecycle_to_trigger(JobState.BLOCKED)
    assert t_block is None


def test_map_lifecycle_to_trigger_for_run() -> None:
    """Verify RunState and RunOutcome map correctly to NotificationTriggers."""
    t_sub = map_lifecycle_to_trigger(RunState.SUBMITTED)
    assert t_sub == NotificationTrigger.SUBMITTED

    t_run = map_lifecycle_to_trigger(RunState.RUNNING)
    assert t_run == NotificationTrigger.STARTED

    t_comp = map_lifecycle_to_trigger(RunState.DONE, RunOutcome.SUCCEEDED)
    assert t_comp == NotificationTrigger.COMPLETED

    t_fail = map_lifecycle_to_trigger(RunState.DONE, RunOutcome.FAILED)
    assert t_fail == NotificationTrigger.FAILED

    t_part_fail = map_lifecycle_to_trigger(RunState.DONE, RunOutcome.PARTIALLY_FAILED)
    assert t_part_fail == NotificationTrigger.FAILED

    t_canc = map_lifecycle_to_trigger(RunState.DONE, RunOutcome.CANCELLED)
    assert t_canc == NotificationTrigger.CANCELLED

    t_block = map_lifecycle_to_trigger(RunState.BLOCKED)
    assert t_block is None
