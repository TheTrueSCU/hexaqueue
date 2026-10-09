"""Tests for get_auth_context authentication and elevation dependency."""

import pytest
from fastapi import HTTPException

from hexaqueue_server.adapters.api.auth import get_auth_context


def test_auth_context_default_identity() -> None:
    """Verify default identity when no headers or query parameters provided."""
    user_id, is_elevated = get_auth_context()
    assert user_id == "default"
    assert is_elevated is False


def test_auth_context_explicit_user_headers_and_query() -> None:
    """Verify explicit user extraction from header or query parameter."""
    user_header, _ = get_auth_context(x_hexaqueue_user="alice")
    assert user_header == "alice"

    user_query, _ = get_auth_context(user="bob")
    assert user_query == "bob"


def test_auth_context_anonymous_admin_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify administrative elevation succeeds when anonymous admin is permitted."""
    monkeypatch.setenv("HEXAQUEUE_ALLOW_ANONYMOUS_ADMIN", "1")
    monkeypatch.delenv("HEXAQUEUE_ADMIN_TOKEN", raising=False)

    user_id, is_elevated = get_auth_context(elevate=True)
    assert user_id == "default"
    assert is_elevated is True


def test_auth_context_anonymous_admin_forbidden_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify elevation without token fails when anonymous admin is not permitted."""
    monkeypatch.setenv("HEXAQUEUE_ALLOW_ANONYMOUS_ADMIN", "0")
    monkeypatch.delenv("HEXAQUEUE_ADMIN_TOKEN", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        get_auth_context(elevate=True)
    status_code = exc_info.value.status_code
    assert status_code == 403


def test_auth_context_configured_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify token validation against configured HEXAQUEUE_ADMIN_TOKEN."""
    monkeypatch.setenv("HEXAQUEUE_ADMIN_TOKEN", "secret-token-123")

    # Invalid token -> 403
    with pytest.raises(HTTPException) as exc_info:
        get_auth_context(elevate=True, admin_token="wrong-token")
    err_status = exc_info.value.status_code
    assert err_status == 403

    # Valid token -> elevated
    user_id, is_elevated = get_auth_context(
        elevate=True, admin_token="secret-token-123"
    )
    assert user_id == "default"
    assert is_elevated is True
