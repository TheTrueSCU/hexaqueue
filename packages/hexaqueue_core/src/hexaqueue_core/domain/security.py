"""Zero-trust security domain models, SPIFFE identity, and cryptographic envelopes.

Notes/Architectural Intent:
    Encapsulates CNCF SPIFFE/SPIRE workload identity value objects, role-based
    boundary authorization policies, AES-256-GCM envelope encryption containers,
    and SIEM-compatible boundary audit records.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SpiffeRole(StrEnum):
    """Canonical workload identity roles in the Hexaqueue cluster."""

    COLLATERAL = "collateral"
    MONITOR = "monitor"
    OPERATOR = "operator"
    SCANNER = "scanner"
    SERVER = "server"
    WORKER = "worker"


class SpiffeId(BaseModel):
    """Parsed and validated CNCF SPIFFE identity value object.

    Args:
        trust_domain: DNS-compatible trust domain (e.g. 'hexaqueue.org').
        path: Path identifying the workload (e.g. '/ns/prod/sa/server').
        uri: Canonical string representation (e.g. 'spiffe://hexaqueue.org/ns/prod/sa/server').
        workload_type: Extracted workload role or classification.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(description="Workload path starting with /")
    trust_domain: str = Field(description="SPIFFE trust domain")
    uri: str = Field(description="Full canonical SPIFFE URI")
    workload_type: str | None = Field(
        default=None, description="Extracted workload role"
    )

    @classmethod
    def parse(cls, uri: str) -> SpiffeId:
        """Parse and validate a raw SPIFFE URI string.

        Args:
            uri: SPIFFE URI string (must start with 'spiffe://').

        Returns:
            Validated SpiffeId value object.

        Raises:
            ValueError: If URI is malformed, scheme is not spiffe, or path is missing.
        """
        if not uri or not isinstance(uri, str):
            msg = "SPIFFE URI must be a non-empty string"
            raise ValueError(msg)

        parsed = urlparse(uri)
        if parsed.scheme != "spiffe":
            msg = f"Invalid SPIFFE URI scheme '{parsed.scheme}'; expected 'spiffe'"
            raise ValueError(msg)

        trust_domain = parsed.netloc.lower()
        if not trust_domain:
            msg = "SPIFFE URI must contain a non-empty trust domain"
            raise ValueError(msg)

        path = parsed.path
        if not path or not path.startswith("/"):
            msg = "SPIFFE URI must contain a path starting with '/'"
            raise ValueError(msg)

        # Detect known workload role from path segments
        segments = [s.lower() for s in path.split("/") if s]
        workload_type: str | None = None
        for role in SpiffeRole:
            if role.value in segments:
                workload_type = role.value
                break

        canonical_uri = f"spiffe://{trust_domain}{path}"
        return cls(
            path=path,
            trust_domain=trust_domain,
            uri=canonical_uri,
            workload_type=workload_type,
        )

    def __str__(self) -> str:
        """Return the canonical SPIFFE URI."""
        return self.uri


class SpiffeAuthorizationPolicy(BaseModel):
    """Zero-trust authorization policy for boundary and route enforcement.

    Args:
        allowed_trust_domains: Set of authorized SPIFFE trust domains.
        role_permissions: Mapping of workload roles to allowed boundary route prefixes.
        exact_spiffe_ids: Whitelist of explicitly authorized exact SPIFFE IDs.
        allow_anonymous: Whether to allow callers without a SPIFFE identity (defaults to False).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    allow_anonymous: bool = Field(
        default=False,
        description="Allow unauthenticated callers (insecure development only)",
    )
    allowed_trust_domains: set[str] = Field(
        default_factory=set, description="Authorized trust domains"
    )
    exact_spiffe_ids: set[str] = Field(
        default_factory=set, description="Explicitly authorized SPIFFE IDs"
    )
    role_permissions: dict[str, set[str]] = Field(
        default_factory=dict, description="Role to allowed boundary prefixes"
    )

    def is_authorized(self, spiffe_id: SpiffeId | str | None, boundary: str) -> bool:
        """Evaluate whether a caller SPIFFE identity is permitted on a target boundary.

        Args:
            spiffe_id: Caller identity (SpiffeId object, URI string, or None).
            boundary: Target boundary route or action path (e.g. 'api:worker:heartbeat').

        Returns:
            True if authorized, False otherwise.
        """
        if spiffe_id is None:
            return self.allow_anonymous

        parsed = (
            spiffe_id
            if isinstance(spiffe_id, SpiffeId)
            else SpiffeId.parse(str(spiffe_id))
        )

        # Check trust domain if constraints are specified
        if (
            self.allowed_trust_domains
            and parsed.trust_domain not in self.allowed_trust_domains
        ):
            return False

        # Exact ID match takes precedence
        if parsed.uri in self.exact_spiffe_ids:
            return True

        # Check role-based boundary permissions
        if parsed.workload_type and parsed.workload_type in self.role_permissions:
            allowed_prefixes = self.role_permissions[parsed.workload_type]
            for prefix in allowed_prefixes:
                if (
                    prefix == "*"
                    or (prefix.endswith("*") and boundary.startswith(prefix[:-1]))
                    or boundary == prefix
                ):
                    return True

        return False


class EncryptedEnvelope(BaseModel):
    """Cryptographic envelope containing AES-256-GCM encrypted payload and wrapped DEK.

    Args:
        ciphertext: Encrypted payload bytes.
        iv: 12-byte initialization vector for AES-GCM.
        tag: 16-byte authentication tag for AES-GCM integrity.
        encrypted_dek: Data Encryption Key wrapped by master Key Encryption Key (KEK).
        key_id: Master key identifier used for wrapping.
        algorithm: Symmetric cipher algorithm (defaults to 'AES-256-GCM').
        context: Additional Authenticated Data (AAD) dictionary bound to the ciphertext.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm: str = Field(
        default="AES-256-GCM", description="Symmetric encryption cipher"
    )
    ciphertext: bytes = Field(description="Encrypted payload bytes")
    context: dict[str, str] = Field(
        default_factory=dict, description="Additional Authenticated Data (AAD)"
    )
    encrypted_dek: bytes = Field(description="Wrapped Data Encryption Key")
    iv: bytes = Field(description="12-byte initialization vector / nonce")
    key_id: str = Field(description="Master Key identifier (KEK)")
    tag: bytes = Field(description="16-byte authentication tag")

    @model_validator(mode="after")
    def validate_envelope_lengths(self) -> Self:
        """Ensure cryptographic component lengths meet AES-GCM requirements."""
        if len(self.iv) != 12:
            msg = f"AES-GCM IV must be exactly 12 bytes; got {len(self.iv)}"
            raise ValueError(msg)
        if len(self.tag) != 16:
            msg = f"AES-GCM authentication tag must be exactly 16 bytes; got {len(self.tag)}"
            raise ValueError(msg)
        return self


class BoundaryAuditRecord(BaseModel):
    """Structured, immutable audit log record for security boundary traversal.

    Args:
        audit_id: Unique record UUID.
        timestamp_utc: ISO timestamp in UTC.
        caller_spiffe_id: SPIFFE URI of the calling workload or client.
        target_boundary: Endpoint or boundary route traversed.
        action: Semantic action performed (e.g. 'SUBMIT', 'HEARTBEAT', 'READ', 'DELETE').
        target_resource_id: Identifier of the primary resource affected.
        authorization_verdict: Authorization outcome ('ALLOWED' or 'DENIED').
        payload_sha256: Cryptographic hash of request payload if present.
        client_ip: Source IP address of the caller.
        duration_ms: Execution duration in milliseconds.
        status_code: HTTP or RPC response code.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str = Field(description="Action executed (e.g. SUBMIT, HEARTBEAT)")
    audit_id: str = Field(
        default_factory=lambda: str(uuid4()), description="Audit event UUID"
    )
    authorization_verdict: str = Field(description="Verdict: ALLOWED or DENIED")
    caller_spiffe_id: str | None = Field(default=None, description="Caller SPIFFE ID")
    client_ip: str | None = Field(default=None, description="Client IP address")
    duration_ms: float = Field(default=0.0, ge=0.0, description="Duration in ms")
    payload_sha256: str | None = Field(default=None, description="SHA-256 of payload")
    status_code: int | None = Field(default=None, description="HTTP/RPC status code")
    target_boundary: str = Field(description="Route or service boundary")
    target_resource_id: str = Field(description="Resource identifier")
    timestamp_utc: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Event UTC timestamp",
    )

    def to_siem_dict(self) -> dict[str, Any]:
        """Convert to SIEM-compatible structured dictionary."""
        return {
            "action": self.action,
            "audit_id": self.audit_id,
            "authorization_verdict": self.authorization_verdict,
            "caller_spiffe_id": self.caller_spiffe_id,
            "client_ip": self.client_ip,
            "duration_ms": self.duration_ms,
            "payload_sha256": self.payload_sha256,
            "status_code": self.status_code,
            "target_boundary": self.target_boundary,
            "target_resource_id": self.target_resource_id,
            "timestamp": self.timestamp_utc.isoformat(),
        }

    def to_siem_json(self) -> str:
        """Serialize to a single-line JSON string for SIEM log forwarders."""
        return json.dumps(self.to_siem_dict())


__all__ = [
    "BoundaryAuditRecord",
    "EncryptedEnvelope",
    "SpiffeAuthorizationPolicy",
    "SpiffeId",
    "SpiffeRole",
]
