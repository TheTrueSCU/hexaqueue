"""Notification trigger flags, policy models, and lifecycle event mappers.

Notes/Architectural Intent:
    Provides domain-level abstractions for multi-granular event notifications
    across runs, jobs, and workflow steps. Implements bitwise trigger flags
    (IntFlag) supporting flexible composition (e.g. ERRORS | COMPLETED),
    lossless serialization, and deterministic mapping from cluster state transitions.
"""

from __future__ import annotations

from enum import IntFlag, auto
from typing import Any

from hexastack_core.ports.notification import NotificationPriority
from pydantic import BaseModel, ConfigDict, Field, field_validator

from hexaqueue_core.domain.lifecycle import (
    JobState,
    RunOutcome,
    RunState,
    TerminalOutcome,
)


def _tokenize_trigger_string(value: str) -> list[str]:
    """Tokenize comma or pipe separated trigger strings."""
    tokens = [value]
    for delim in (",", "|"):
        tokens = [part for token in tokens for part in token.split(delim)]
    return [t.strip().upper() for t in tokens if t.strip()]


def _resolve_single_trigger(
    name: str, trigger_cls: type[NotificationTrigger]
) -> NotificationTrigger:
    """Resolve a single string token to a NotificationTrigger member."""
    try:
        member = getattr(trigger_cls, name)
        if isinstance(member, trigger_cls):
            return member
    except AttributeError:
        pass
    valid_names = [m.name for m in trigger_cls]
    raise ValueError(
        f"Unknown notification trigger '{name}'. Valid triggers: {valid_names}"
    )


class NotificationTrigger(IntFlag):
    """Bitwise lifecycle triggers activating notification policies.

    Notes/Architectural Intent:
        Inherits from IntFlag to enable bitwise combination (e.g. FAILED | TIMED_OUT),
        sub-millisecond membership testing, compact bitmask wire-format serialization,
        and convenient string alias expansion (e.g. ERRORS, TERMINAL, ALL).
    """

    NONE = 0
    SUBMITTED = auto()
    STARTED = auto()
    RESUMED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()
    TIMED_OUT = auto()
    PREEMPTED = auto()

    # Pre-defined composite bitmasks
    ERRORS = FAILED | TIMED_OUT | PREEMPTED
    TERMINAL = COMPLETED | CANCELLED | ERRORS
    ALL = SUBMITTED | STARTED | RESUMED | TERMINAL

    @classmethod
    def parse(
        cls, value: str | int | NotificationTrigger | list[Any]
    ) -> NotificationTrigger:
        """Parse arbitrary user input (string, int, list, or enum) into a NotificationTrigger flag.

        Args:
            value: A single string ('COMPLETED,FAILED' or 'ERRORS'), integer bitmask,
                existing NotificationTrigger instance, or list of trigger names/instances.

        Returns:
            Resolved composite NotificationTrigger.

        Raises:
            ValueError: If an unknown trigger name or invalid format is provided.
        """
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            return cls(value)
        if isinstance(value, list):
            result = cls.NONE
            for item in value:
                result |= cls.parse(item)
            return result
        if isinstance(value, str):
            return cls._parse_str(value)

        raise ValueError(
            f"Cannot parse NotificationTrigger from type {type(value).__name__}: {value}"
        )

    @classmethod
    def _parse_str(cls, value: str) -> NotificationTrigger:
        """Parse string representations into composite trigger flags."""
        clean_str = value.strip()
        if not clean_str:
            return cls.NONE
        if clean_str.isdigit():
            return cls(int(clean_str))

        result = cls.NONE
        for token in _tokenize_trigger_string(clean_str):
            result |= _resolve_single_trigger(token, cls)
        return result

    def matches(self, trigger: NotificationTrigger) -> bool:
        """Check whether this composite flag matches an active single trigger event.

        Args:
            trigger: The single lifecycle event trigger to evaluate.

        Returns:
            True if the trigger bit is set within this flag, False otherwise.
        """
        return bool(self.value & trigger.value)


class NotificationPolicy(BaseModel):
    """Specification for dispatching alerts when lifecycle triggers fire.

    Args:
        targets: List of Apprise-compatible service destination URIs
            (e.g. 'slack://...', 'mailto://...', 'ntfy://...').
        triggers: Bitwise triggers that activate notification delivery.
        priority: Baseline urgency priority passed to NotificationPort.
        escalate_on_error: Automatically elevate priority to HIGH or EMERGENCY
            on failure or timeout outcomes.
        tags: Optional categorization tags or channel topics.
        template: Optional custom markdown/plaintext body template.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    targets: list[str] = Field(
        default_factory=list,
        description="Destination service URIs (e.g. slack://token/channel, mailto://user@domain)",
    )
    triggers: NotificationTrigger = Field(
        default=NotificationTrigger.ERRORS,
        description="Bitwise lifecycle triggers that activate this policy",
    )
    priority: NotificationPriority = Field(
        default=NotificationPriority.NORMAL,
        description="Default semantic urgency level",
    )
    escalate_on_error: bool = Field(
        default=True,
        description="Whether to elevate priority to HIGH/EMERGENCY on failure or timeout",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Categorization tags or channel targets",
    )
    template: str | None = Field(
        default=None,
        description="Optional custom message template",
    )

    @field_validator("triggers", mode="before")
    @classmethod
    def _validate_triggers(cls, value: Any) -> NotificationTrigger:
        """Coerce strings, ints, and lists into a validated NotificationTrigger flag."""
        return NotificationTrigger.parse(value)

    @field_validator("targets")
    @classmethod
    def _validate_targets(cls, value: list[str]) -> list[str]:
        """Strip whitespace and reject empty destination URIs."""
        return [t.strip() for t in value if t.strip()]


def map_lifecycle_to_trigger(
    state: JobState | RunState,
    outcome: TerminalOutcome | RunOutcome | None = None,
) -> NotificationTrigger | None:
    """Deterministically map a lifecycle state and outcome to a NotificationTrigger.

    Args:
        state: Current JobState or RunState.
        outcome: Optional terminal outcome if state is DONE.

    Returns:
        Matching NotificationTrigger if the state change corresponds to a monitored event,
        or None if the state is transient/unmonitored.

    Notes/Architectural Intent:
        Decouples internal state machine representations from notification trigger bits.
    """
    if state in (JobState.SUBMITTED, RunState.SUBMITTED):
        return NotificationTrigger.SUBMITTED
    if state in (JobState.RUNNING, RunState.RUNNING):
        return NotificationTrigger.STARTED
    if state in (JobState.DONE, RunState.DONE):
        if outcome in (TerminalOutcome.COMPLETED, RunOutcome.SUCCEEDED):
            return NotificationTrigger.COMPLETED
        if outcome in (
            TerminalOutcome.FAILED,
            RunOutcome.FAILED,
            RunOutcome.PARTIALLY_FAILED,
        ):
            return NotificationTrigger.FAILED
        if outcome in (TerminalOutcome.CANCELLED, RunOutcome.CANCELLED):
            return NotificationTrigger.CANCELLED
        if outcome == TerminalOutcome.TIMED_OUT:
            return NotificationTrigger.TIMED_OUT
        if outcome == TerminalOutcome.PREEMPTED:
            return NotificationTrigger.PREEMPTED

    return None


__all__ = [
    "map_lifecycle_to_trigger",
    "NotificationPolicy",
    "NotificationTrigger",
]
