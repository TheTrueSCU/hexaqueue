"""Hexaqueue root domain and infrastructure exception hierarchy.

Notes/Architectural Intent:
    Specializes HexastackError so that all Hexaqueue domain errors integrate
    seamlessly with Hexastack error handlers, CQRS middleware, and REST/gRPC
    exception mappings.
"""

from hexastack_core.domain.exceptions import HexastackError


class HexaqueueError(HexastackError):
    """Base exception for all Hexaqueue domain, scheduler, and infrastructure errors."""


class HexaqueueConfigError(HexaqueueError):
    """Exception raised when configuration parsing, loading, or section resolution fails."""


class FreeTierLimitExceededError(HexaqueueError):
    """Exception raised when a job or provisioning request exceeds the active CSP Free-Tier cap."""


class ChecksumMismatchError(HexaqueueError):
    """Exception raised when actual uploaded collateral SHA-256 does not match registered digest."""


class QuotaExceededError(HexaqueueError):
    """Exception raised when a user, team, or project exceeds allocated compute or budget quota."""


class JobStateTransitionError(HexaqueueError):
    """Exception raised when an illegal job or run lifecycle state transition is attempted."""


__all__ = [
    "ChecksumMismatchError",
    "FreeTierLimitExceededError",
    "HexaqueueConfigError",
    "HexaqueueError",
    "JobStateTransitionError",
    "QuotaExceededError",
]
