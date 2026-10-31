"""Security adapters for Hexaqueue Core."""

from hexaqueue_core.adapters.security.audit import (
    InMemoryBoundaryAuditLoggerAdapter,
)
from hexaqueue_core.adapters.security.encryption import (
    LocalEnvelopeEncryptionAdapter,
)
from hexaqueue_core.adapters.security.noop import (
    NoOpSecurityQuarantineAdapter,
)
from hexaqueue_core.adapters.security.spiffe import (
    LocalWorkloadIdentityAdapter,
    PolicySpiffeAuthorizerAdapter,
)

__all__ = [
    "InMemoryBoundaryAuditLoggerAdapter",
    "LocalEnvelopeEncryptionAdapter",
    "LocalWorkloadIdentityAdapter",
    "NoOpSecurityQuarantineAdapter",
    "PolicySpiffeAuthorizerAdapter",
]
