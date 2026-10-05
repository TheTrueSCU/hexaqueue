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


class JobStateTransitionError(HexaqueueError):
    """Exception raised when an illegal job or run lifecycle state transition is attempted."""


class PermissionDeniedError(HexaqueueError):
    """Exception raised when an unauthorized user attempts an operation or unpermitted elevation."""


class QuotaExceededError(HexaqueueError):
    """Exception raised when a user, team, or project exceeds allocated compute or budget quota."""


class GpuAllocationError(HexaqueueError):
    """Exception raised when dynamic GPU device allocation fails or cannot be satisfied."""


class StorageVolumeError(HexaqueueError):
    """Exception raised when scratch volume allocation, quota, or mounting fails."""


class SuiteCompilationError(HexaqueueError):
    """Exception raised when hierarchical suite compilation or validation fails."""


class VariableInterpolationError(SuiteCompilationError):
    """Exception raised when an unresolved or leaked template variable is encountered."""


__all__ = [
    "ChecksumMismatchError",
    "FreeTierLimitExceededError",
    "GpuAllocationError",
    "HexaqueueConfigError",
    "HexaqueueError",
    "JobStateTransitionError",
    "PermissionDeniedError",
    "QuotaExceededError",
    "StorageVolumeError",
    "SuiteCompilationError",
    "VariableInterpolationError",
]
