"""Unit tests for ZeroTrustBoundaryMiddleware and SIEM audit logging."""

from starlette.testclient import TestClient

from hexaqueue_core.adapters.security.audit import InMemoryBoundaryAuditLoggerAdapter
from hexaqueue_core.adapters.security.spiffe import PolicySpiffeAuthorizerAdapter
from hexaqueue_core.domain.security import SpiffeAuthorizationPolicy
from hexaqueue_server.adapters.api.app import create_server_app
from hexaqueue_server.domain.config import ServerConfig, ServerSecurityConfig


def test_zero_trust_middleware_default_allows_anonymous() -> None:
    """Verify default server config allows requests and records ALLOWED audit log."""
    app = create_server_app()
    client = TestClient(app)

    res = client.get("/v1/nodes")
    status = res.status_code
    assert status == 200

    audit_logger: InMemoryBoundaryAuditLoggerAdapter = app.state.audit_logger

    # Retrieve synchronously from internal deque for testing
    recent = list(audit_logger._records)
    cnt = len(recent)
    assert cnt >= 1
    last_record = recent[-1]
    verdict = last_record.authorization_verdict
    assert verdict == "ALLOWED"
    boundary = last_record.target_boundary
    assert boundary == "rest:get:/v1/nodes"


def test_zero_trust_middleware_spiffe_enforced_denies_anonymous() -> None:
    """Verify enforcing SPIFFE rejects anonymous callers with 401."""
    sec_cfg = ServerSecurityConfig(spiffe_enabled=True, allow_anonymous=False)
    cfg = ServerConfig(security=sec_cfg)
    app = create_server_app(config=cfg)

    policy = SpiffeAuthorizationPolicy(
        allow_anonymous=False,
        allowed_trust_domains={"hexaqueue.org"},
    )
    app.state.spiffe_authorizer = PolicySpiffeAuthorizerAdapter(policy)

    client = TestClient(app)
    res = client.get("/v1/nodes")
    status = res.status_code
    assert status == 401
    detail = res.json().get("detail", "")
    assert "SPIFFE identity required" in detail

    audit_logger: InMemoryBoundaryAuditLoggerAdapter = app.state.audit_logger
    recent = list(audit_logger._records)
    assert len(recent) >= 1
    last_record = recent[-1]
    assert last_record.authorization_verdict == "DENIED"
    assert last_record.status_code == 401


def test_zero_trust_middleware_spiffe_enforced_allows_valid_caller() -> None:
    """Verify valid SPIFFE caller is permitted when authorized by policy."""
    sec_cfg = ServerSecurityConfig(spiffe_enabled=True, allow_anonymous=False)
    cfg = ServerConfig(security=sec_cfg)
    app = create_server_app(config=cfg)

    policy = SpiffeAuthorizationPolicy(
        allowed_trust_domains={"hexaqueue.org"},
        role_permissions={"worker": {"rest:get:/v1/nodes"}},
    )
    app.state.spiffe_authorizer = PolicySpiffeAuthorizerAdapter(policy)

    client = TestClient(app)
    res = client.get(
        "/v1/nodes",
        headers={"X-SPIFFE-ID": "spiffe://hexaqueue.org/worker/node-42"},
    )
    status = res.status_code
    assert status == 200

    audit_logger: InMemoryBoundaryAuditLoggerAdapter = app.state.audit_logger
    recent = list(audit_logger._records)
    assert len(recent) >= 1
    last_record = recent[-1]
    assert last_record.authorization_verdict == "ALLOWED"
    assert last_record.caller_spiffe_id == "spiffe://hexaqueue.org/worker/node-42"


def test_zero_trust_middleware_spiffe_enforced_denies_unauthorized_role() -> None:
    """Verify known SPIFFE caller lacking role permission is rejected with 403."""
    sec_cfg = ServerSecurityConfig(spiffe_enabled=True, allow_anonymous=False)
    cfg = ServerConfig(security=sec_cfg)
    app = create_server_app(config=cfg)

    policy = SpiffeAuthorizationPolicy(
        allowed_trust_domains={"hexaqueue.org"},
        role_permissions={"scanner": {"rest:get:/v1/scanner"}},
    )
    app.state.spiffe_authorizer = PolicySpiffeAuthorizerAdapter(policy)

    client = TestClient(app)
    # Scanner tries to access worker nodes endpoint
    res = client.get(
        "/v1/nodes",
        headers={"X-SPIFFE-ID": "spiffe://hexaqueue.org/scanner/daemon-1"},
    )
    status = res.status_code
    assert status == 403
    detail = res.json().get("detail", "")
    assert "not authorized" in detail

    audit_logger: InMemoryBoundaryAuditLoggerAdapter = app.state.audit_logger
    recent = list(audit_logger._records)
    assert len(recent) >= 1
    last_record = recent[-1]
    assert last_record.authorization_verdict == "DENIED"
    assert last_record.status_code == 403
