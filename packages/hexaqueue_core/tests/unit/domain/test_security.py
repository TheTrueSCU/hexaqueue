"""Unit tests for zero-trust security domain models."""

from datetime import UTC, datetime

import pytest

from hexaqueue_core.domain.security import (
    BoundaryAuditRecord,
    EncryptedEnvelope,
    SpiffeAuthorizationPolicy,
    SpiffeId,
    SpiffeRole,
)


def test_spiffe_id_parsing() -> None:
    """Verify valid SPIFFE URI parsing and role extraction."""
    spiffe = SpiffeId.parse("spiffe://hexaqueue.org/ns/prod/sa/server")
    td = spiffe.trust_domain
    assert td == "hexaqueue.org"
    path = spiffe.path
    assert path == "/ns/prod/sa/server"
    wtype = spiffe.workload_type
    assert wtype == "server"
    uri_str = str(spiffe)
    assert uri_str == "spiffe://hexaqueue.org/ns/prod/sa/server"


def test_spiffe_id_worker_role() -> None:
    """Verify worker role detection from path."""
    spiffe = SpiffeId.parse("spiffe://compute.hpc.org/worker/gpu-node-01")
    td = spiffe.trust_domain
    assert td == "compute.hpc.org"
    wtype = spiffe.workload_type
    assert wtype == SpiffeRole.WORKER.value


def test_spiffe_id_invalid_uris() -> None:
    """Verify malformed SPIFFE URIs raise ValueError."""
    with pytest.raises(ValueError, match="Invalid SPIFFE URI scheme"):
        SpiffeId.parse("https://hexaqueue.org/worker/1")

    with pytest.raises(ValueError, match="trust domain"):
        SpiffeId.parse("spiffe:///missing-trust-domain")

    with pytest.raises(ValueError, match="non-empty string"):
        SpiffeId.parse("")  # type: ignore[arg-type]


def test_spiffe_authorization_policy_eval() -> None:
    """Verify trust domain, exact ID, and role-based policy evaluation."""
    policy = SpiffeAuthorizationPolicy(
        allowed_trust_domains={"hexaqueue.org"},
        role_permissions={"worker": {"api:worker:*", "rest:post:/v1/nodes/heartbeat"}},
        exact_spiffe_ids={"spiffe://hexaqueue.org/admin/root"},
    )

    worker_id = SpiffeId.parse("spiffe://hexaqueue.org/worker/node-12")
    foreign_id = SpiffeId.parse("spiffe://attacker.org/worker/node-12")
    admin_id = SpiffeId.parse("spiffe://hexaqueue.org/admin/root")

    worker_auth = policy.is_authorized(worker_id, "api:worker:lease")
    assert worker_auth is True

    worker_denied = policy.is_authorized(worker_id, "api:admin:shutdown")
    assert worker_denied is False

    foreign_denied = policy.is_authorized(foreign_id, "api:worker:lease")
    assert foreign_denied is False

    admin_auth = policy.is_authorized(admin_id, "api:admin:shutdown")
    assert admin_auth is True

    anon_denied = policy.is_authorized(None, "api:worker:lease")
    assert anon_denied is False


def test_spiffe_authorization_policy_allow_anonymous() -> None:
    """Verify anonymous access is allowed only when explicitly configured."""
    dev_policy = SpiffeAuthorizationPolicy(allow_anonymous=True)
    anon_allowed = dev_policy.is_authorized(None, "api:any:endpoint")
    assert anon_allowed is True


def test_encrypted_envelope_validation() -> None:
    """Verify EncryptedEnvelope length constraints."""
    valid_env = EncryptedEnvelope(
        ciphertext=b"encrypted-bytes",
        iv=b"0" * 12,
        tag=b"1" * 16,
        encrypted_dek=b"wrapped-dek-bytes",
        key_id="kek-1",
        context={"tenant": "acme"},
    )
    algo = valid_env.algorithm
    assert algo == "AES-256-GCM"

    with pytest.raises(ValueError, match="IV must be exactly 12 bytes"):
        EncryptedEnvelope(
            ciphertext=b"data",
            iv=b"too-short",
            tag=b"1" * 16,
            encrypted_dek=b"wrapped",
            key_id="kek",
        )

    with pytest.raises(ValueError, match="tag must be exactly 16 bytes"):
        EncryptedEnvelope(
            ciphertext=b"data",
            iv=b"0" * 12,
            tag=b"too-short",
            encrypted_dek=b"wrapped",
            key_id="kek",
        )


def test_boundary_audit_record_siem_serialization() -> None:
    """Verify SIEM structured JSON serialization."""
    record = BoundaryAuditRecord(
        caller_spiffe_id="spiffe://hexaqueue.org/worker/node-1",
        target_boundary="rest:post:/v1/jobs/submit",
        action="POST",
        target_resource_id="job-99",
        authorization_verdict="ALLOWED",
        payload_sha256="abc123sha",
        client_ip="192.168.1.10",
        duration_ms=4.5,
        status_code=200,
        timestamp_utc=datetime.now(UTC),
    )
    siem_dict = record.to_siem_dict()
    assert siem_dict["action"] == "POST"
    assert siem_dict["authorization_verdict"] == "ALLOWED"
    assert siem_dict["caller_spiffe_id"] == "spiffe://hexaqueue.org/worker/node-1"

    siem_json = record.to_siem_json()
    assert '"authorization_verdict": "ALLOWED"' in siem_json
    assert '"target_boundary": "rest:post:/v1/jobs/submit"' in siem_json
