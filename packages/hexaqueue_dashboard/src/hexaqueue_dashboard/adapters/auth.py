"""Hexastack-Auth JWT, RBAC, and HTTPS transport enforcement for Hexaqueue Dashboard.

Notes/Architectural Intent:
    Replaces spoofable header-based identity with cryptographic JWT validation
    and PBKDF2 password verification from `hexastack-auth`. Enforces distinct
    principals (`rjdw` as `admin`, `hexaqueue-ci` as `ci`), `HttpOnly`/`Secure`
    session cookies, and HTTPS/loopback transport checks for Tailscale Serve
    and SSH-tunneled deployments.
"""

from __future__ import annotations

import os
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from hexastack_auth.adapters.jwt import JwtSecurityAdapter
from hexastack_auth.adapters.password import Pbkdf2PasswordHasher
from hexastack_auth.domain.exceptions import AuthError
from hexastack_auth.domain.models import Identity
from pydantic import BaseModel, Field

SESSION_COOKIE_NAME = "hexaqueue_session"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


class LoginRequest(BaseModel):
    """Dashboard credential login payload.

    Notes/Architectural Intent:
        Accepts username and password/token for exchange into a signed JWT
        and HttpOnly session cookie.
    """

    username: str = Field(
        ..., min_length=1, description="Principal username (e.g. rjdw)"
    )
    password: str = Field(..., min_length=1, description="Web/API credential secret")


class AuthStatusResponse(BaseModel):
    """Authenticated principal metadata returned by auth endpoints.

    Notes/Architectural Intent:
        Exposes resolved identity and RBAC role flags without leaking secrets.
    """

    user_id: str = Field(..., description="Authenticated principal identifier")
    roles: list[str] = Field(default_factory=list, description="Assigned RBAC roles")
    is_admin: bool = Field(
        default=False, description="True if principal holds admin role"
    )
    access_token: str | None = Field(
        default=None, description="Bearer JWT returned on login"
    )
    token_type: str = Field(default="bearer", description="Token scheme")


def is_https_request(request: Request) -> bool:
    """Return True if the inbound request arrived over HTTPS.

    Args:
        request: Active FastAPI/Starlette Request.

    Returns:
        True when scheme is https or X-Forwarded-Proto indicates https.
    """
    if request.url.scheme.lower() == "https":
        return True
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return forwarded_proto.split(",")[0].strip().lower() == "https"


def is_loopback_request(request: Request) -> bool:
    """Return True if the inbound request originates from or targets loopback.

    Args:
        request: Active FastAPI/Starlette Request.

    Returns:
        True for localhost / 127.0.0.1 / ::1 / Starlette TestClient requests.
    """
    if request.headers.get("x-forwarded-for"):
        return False
    client_host = request.client.host if request.client else ""
    url_host = (request.url.hostname or "").lower()
    return client_host in _LOOPBACK_HOSTS or url_host in _LOOPBACK_HOSTS


def enforce_https_transport(request: Request) -> None:
    """Reject non-HTTPS, non-loopback requests when HTTPS enforcement is active.

    Args:
        request: Active FastAPI/Starlette Request.

    Raises:
        HTTPException: 403 Forbidden if plaintext HTTP is used over a non-loopback path.
    """
    require_https = os.environ.get("HEXAQUEUE_REQUIRE_HTTPS", "1") != "0"
    if not require_https:
        return
    if is_https_request(request) or is_loopback_request(request):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="HTTPS is required for Hexaqueue Dashboard access.",
    )


class DashboardAuthManager:
    """Coordinates `hexastack-auth` credential verification and JWT issuance.

    Notes/Architectural Intent:
        Keeps web/dashboard credentials (`rjdw`) and CI API credentials
        (`hexaqueue-ci`) strictly separated from OCI SSH keys, deriving roles
        (`admin` vs `ci`) deterministically from verified identities.
    """

    def __init__(
        self,
        *,
        jwt_secret: str | None = None,
        admin_user: str | None = None,
        admin_password_hash: str | None = None,
        ci_user: str | None = None,
        ci_token_hash: str | None = None,
        ttl_seconds: int = 3600,
    ) -> None:
        """Initialize the dashboard authentication manager.

        Args:
            jwt_secret: HMAC secret for signing/verifying JWTs.
            admin_user: Primary admin principal name (default 'rjdw').
            admin_password_hash: PBKDF2 password hash for admin user.
            ci_user: Subordinate CI principal name (default 'hexaqueue-ci').
            ci_token_hash: PBKDF2 hash for CI principal credential.
            ttl_seconds: Issued JWT lifetime in seconds.
        """
        effective_secret = (
            jwt_secret
            or os.environ.get("HEXAQUEUE_JWT_SECRET")
            or secrets.token_urlsafe(32)
        )
        self._jwt = JwtSecurityAdapter(
            secret_key=effective_secret,
            default_ttl_seconds=ttl_seconds,
            issuer="hexaqueue",
        )
        self._hasher = Pbkdf2PasswordHasher()
        self.admin_user = admin_user or os.environ.get("HEXAQUEUE_ADMIN_USER", "rjdw")
        self.admin_password_hash = admin_password_hash or os.environ.get(
            "HEXAQUEUE_ADMIN_PASSWORD_HASH"
        )
        self.ci_user = ci_user or os.environ.get("HEXAQUEUE_CI_USER", "hexaqueue-ci")
        self.ci_token_hash = ci_token_hash or os.environ.get("HEXAQUEUE_CI_TOKEN_HASH")

    def hash_secret(self, plaintext: str) -> str:
        """Hash a plaintext password or CI token using PBKDF2-HMAC-SHA256.

        Args:
            plaintext: Raw secret string.

        Returns:
            Encoded PBKDF2 hash string.
        """
        return self._hasher.hash_password(plaintext)

    def authenticate_user(self, username: str, password: str) -> Identity:
        """Verify username and secret against configured RBAC principals.

        Args:
            username: Submitted principal name.
            password: Submitted web password or CI API token.

        Returns:
            Authenticated Identity with assigned RBAC roles.

        Raises:
            HTTPException: 401 Unauthorized if credentials are invalid or unconfigured.
        """
        normalized = username.strip()
        if (
            normalized == self.admin_user
            and self.admin_password_hash
            and self._hasher.verify_password(password, self.admin_password_hash)
        ):
            return Identity(
                user_id=self.admin_user,
                roles=frozenset({"admin"}),
                is_authenticated=True,
            )
        if (
            normalized == self.ci_user
            and self.ci_token_hash
            and self._hasher.verify_password(password, self.ci_token_hash)
        ):
            return Identity(
                user_id=self.ci_user,
                roles=frozenset({"ci"}),
                is_authenticated=True,
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or credential.",
        )

    def issue_token(self, identity: Identity) -> str:
        """Issue a signed JWT for an authenticated Identity.

        Args:
            identity: Verified Identity object.

        Returns:
            Signed JWT string.
        """
        return self._jwt.create_token(identity)

    def verify_token(self, token: str) -> Identity:
        """Verify a JWT string and return the decoded Identity.

        Args:
            token: Raw JWT string.

        Returns:
            Verified Identity object.

        Raises:
            HTTPException: 401 Unauthorized if token is invalid or expired.
        """
        try:
            return self._jwt.verify_token(token)
        except AuthError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid or expired authentication token: {exc}",
            ) from exc


def extract_bearer_or_cookie_token(request: Request) -> str | None:
    """Extract JWT from Authorization Bearer header or HttpOnly session cookie.

    Args:
        request: Active FastAPI/Starlette Request.

    Returns:
        Token string if present, otherwise None.
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            return token
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        return cookie_token.strip()
    return None


def get_auth_manager(request: Request) -> DashboardAuthManager:
    """Resolve or lazily bind DashboardAuthManager on FastAPI application state.

    Args:
        request: Active FastAPI/Starlette Request.

    Returns:
        Configured DashboardAuthManager instance.
    """
    manager = getattr(request.app.state, "auth_manager", None)
    if manager is None:
        manager = DashboardAuthManager()
        request.app.state.auth_manager = manager
    return manager


def create_auth_router() -> APIRouter:
    """Construct `/auth` routes for Dashboard login, logout, and identity inspection.

    Returns:
        APIRouter mounted under the dashboard prefix.
    """
    router = APIRouter(prefix="/auth", tags=["Dashboard Auth"])

    @router.post(
        "/login",
        response_model=AuthStatusResponse,
        summary="Authenticate user or CI principal and issue HttpOnly JWT session",
    )
    def login(
        payload: LoginRequest,
        request: Request,
        response: Response,
        manager: Annotated[DashboardAuthManager, Depends(get_auth_manager)],
    ) -> AuthStatusResponse:
        enforce_https_transport(request)
        identity = manager.authenticate_user(payload.username, payload.password)
        token = manager.issue_token(identity)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            httponly=True,
            secure=is_https_request(request),
            samesite="lax",
            max_age=3600,
            path="/",
        )
        return AuthStatusResponse(
            user_id=identity.user_id,
            roles=sorted(identity.roles),
            is_admin="admin" in identity.roles,
            access_token=token,
        )

    @router.post(
        "/logout",
        summary="Clear Dashboard HttpOnly session cookie",
    )
    def logout(request: Request, response: Response) -> dict[str, Any]:
        enforce_https_transport(request)
        response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
        return {"status": "logged_out"}

    @router.get(
        "/me",
        response_model=AuthStatusResponse,
        summary="Return currently authenticated principal and RBAC roles",
    )
    def me(
        request: Request,
        manager: Annotated[DashboardAuthManager, Depends(get_auth_manager)],
    ) -> AuthStatusResponse:
        enforce_https_transport(request)
        token = extract_bearer_or_cookie_token(request)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
        identity = manager.verify_token(token)
        return AuthStatusResponse(
            user_id=identity.user_id,
            roles=sorted(identity.roles),
            is_admin="admin" in identity.roles,
        )

    return router


__all__ = [
    "AuthStatusResponse",
    "create_auth_router",
    "DashboardAuthManager",
    "enforce_https_transport",
    "extract_bearer_or_cookie_token",
    "get_auth_manager",
    "is_https_request",
    "is_loopback_request",
    "LoginRequest",
    "SESSION_COOKIE_NAME",
]
