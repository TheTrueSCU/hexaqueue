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
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from hexastack_auth.adapters.jwt import JwtSecurityAdapter
from hexastack_auth.adapters.password import Pbkdf2PasswordHasher
from hexastack_auth.domain.exceptions import AuthError
from hexastack_auth.domain.models import Identity
from pydantic import BaseModel, Field, SecretStr

from hexaqueue_dashboard.adapters.rbac_store import create_rbac_policy_store
from hexaqueue_dashboard.domain.rbac import RbacPrincipal
from hexaqueue_dashboard.ports.rbac import RbacPolicyPort

SESSION_COOKIE_NAME = "hexaqueue_session"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


class LoginRequest(BaseModel):
    """Dashboard credential login payload.

    Notes/Architectural Intent:
        Uses `SecretStr` so credentials are redacted in repr/logs and only
        unwrapped transiently during constant-time hash verification.
    """

    username: str = Field(
        ..., min_length=1, description="Principal username (e.g. rjdw)"
    )
    password: SecretStr = Field(
        ..., min_length=1, description="Web/API credential secret (redacted in logs)"
    )


class PrincipalUpsertRequest(BaseModel):
    """Admin request payload to create or update an RBAC principal in the policy store.

    Notes/Architectural Intent:
        Requires a pre-derived PBKDF2 hash (`hashed_secret`) so plaintext
        secrets are never transmitted to or logged by RBAC management endpoints.
    """

    principal_id: str = Field(..., min_length=1, description="Unique principal name")
    hashed_secret: str = Field(
        ..., min_length=1, description="Pre-derived PBKDF2 password or token hash"
    )
    roles: list[str] = Field(
        default_factory=lambda: ["guest"],
        description="Assigned RBAC roles (defaults to ['guest'])",
    )
    permissions: list[str] = Field(
        default_factory=list,
        description="Optional fine-grained permission grants",
    )
    is_active: bool = Field(default=True, description="Whether principal is active")


class PrincipalSummaryResponse(BaseModel):
    """Sanitized RBAC principal summary (never exposes credential hashes)."""

    principal_id: str
    roles: list[str]
    permissions: list[str]
    is_active: bool


class RotatePasswordRequest(BaseModel):
    """Request payload for self-service password rotation.

    Notes/Architectural Intent:
        Uses SecretStr for both current and new credentials so plaintext values
        are masked in Pydantic representations and never written to logs.
    """

    username: str = Field(..., min_length=1, description="Principal username")
    current_secret: SecretStr = Field(
        ..., min_length=1, description="Existing password or token"
    )
    new_secret: SecretStr = Field(
        ..., min_length=1, description="Replacement password or token"
    )


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
        rbac_store: RbacPolicyPort | None = None,
        admin_user: str | None = None,
        admin_password_hash: str | None = None,
        ci_user: str | None = None,
        ci_token_hash: str | None = None,
        ttl_seconds: int = 3600,
    ) -> None:
        """Initialize the dashboard authentication manager.

        Args:
            jwt_secret: HMAC secret for signing/verifying JWTs.
            rbac_store: Port-backed RBAC policy store (Oracle ADB, SQLite, or memory).
            admin_user: Optional bootstrap admin principal name.
            admin_password_hash: Optional PBKDF2 password hash for bootstrap admin.
            ci_user: Optional bootstrap CI principal name.
            ci_token_hash: Optional PBKDF2 hash for bootstrap CI credential.
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
        self._rbac_store = rbac_store or create_rbac_policy_store()
        self._seed_bootstrap_principal(
            principal_id=admin_user or os.environ.get("HEXAQUEUE_ADMIN_USER", "rjdw"),
            hashed_secret=admin_password_hash
            or os.environ.get("HEXAQUEUE_ADMIN_PASSWORD_HASH"),
            roles=frozenset({"admin", "user"}),
        )
        self._seed_bootstrap_principal(
            principal_id=ci_user or os.environ.get("HEXAQUEUE_CI_USER", "hexaqueue-ci"),
            hashed_secret=ci_token_hash or os.environ.get("HEXAQUEUE_CI_TOKEN_HASH"),
            roles=frozenset({"ci"}),
        )

    def _seed_bootstrap_principal(
        self,
        *,
        principal_id: str,
        hashed_secret: str | None,
        roles: frozenset[str],
    ) -> None:
        """Seed or merge roles for an env-configured bootstrap principal."""
        if not hashed_secret:
            return
        existing = self._rbac_store.get_principal(principal_id)
        if existing is None:
            self._rbac_store.upsert_principal(
                RbacPrincipal(
                    principal_id=principal_id,
                    hashed_secret=hashed_secret,
                    roles=roles,
                )
            )
        elif not roles.issubset(existing.roles):
            self._rbac_store.upsert_principal(
                RbacPrincipal(
                    principal_id=existing.principal_id,
                    hashed_secret=existing.hashed_secret,
                    roles=existing.roles | roles,
                )
            )

    @property
    def rbac_store(self) -> RbacPolicyPort:
        """Return the underlying RbacPolicyPort store."""
        return self._rbac_store

    def hash_secret(self, plaintext: str) -> str:
        """Hash a plaintext password or CI token using PBKDF2-HMAC-SHA256.

        Args:
            plaintext: Raw secret string.

        Returns:
            Encoded PBKDF2 hash string.
        """
        return self._hasher.hash_password(plaintext)

    def authenticate_user(self, username: str, password: str) -> Identity:
        """Verify username and secret against the configured RbacPolicyPort store.

        Args:
            username: Submitted principal name.
            password: Submitted credential unwrapped transiently for verification.

        Returns:
            Authenticated Identity with assigned RBAC roles and permissions.

        Raises:
            HTTPException: 401 Unauthorized if credentials are invalid or inactive.
        """
        principal = self._rbac_store.get_principal(username.strip())
        if (
            principal is not None
            and principal.is_active
            and self._hasher.verify_password(password, principal.hashed_secret)
        ):
            return Identity(
                user_id=principal.principal_id,
                roles=principal.roles,
                permissions=principal.permissions,
                is_authenticated=True,
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or credential.",
        )

    def rotate_password(
        self,
        username: str,
        current_secret: SecretStr,
        new_secret: SecretStr,
    ) -> RbacPrincipal:
        """Verify existing credential and rotate a principal's PBKDF2 hash.

        Args:
            username: Principal identifier to update.
            current_secret: Existing credential wrapped in SecretStr.
            new_secret: Replacement credential wrapped in SecretStr.

        Returns:
            Updated RbacPrincipal with preserved roles and permissions.

        Raises:
            HTTPException: 401 Unauthorized if current credential is invalid.
        """
        identity = self.authenticate_user(username, current_secret.get_secret_value())
        existing = self._rbac_store.get_principal(identity.user_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Principal '{identity.user_id}' not found in RBAC store.",
            )
        new_hash = self.hash_secret(new_secret.get_secret_value())
        updated = RbacPrincipal(
            principal_id=existing.principal_id,
            hashed_secret=new_hash,
            roles=existing.roles,
            permissions=existing.permissions,
            is_active=existing.is_active,
        )
        self._rbac_store.upsert_principal(updated)
        return updated

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


def require_roles(
    *roles: str,
    match_all: bool = False,
) -> Callable[..., Identity]:
    """Create a FastAPI dependency requiring an authenticated principal with given role(s).

    Args:
        *roles: Allowed or required role names. If empty, any authenticated user passes.
        match_all: If True, caller must hold all specified roles; if False, any one suffices.

    Returns:
        FastAPI dependency callable resolving to the verified Identity.
    """
    required = frozenset(roles)

    def _dependency(
        request: Request,
        manager: Annotated[DashboardAuthManager, Depends(get_auth_manager)],
    ) -> Identity:
        enforce_https_transport(request)
        token = extract_bearer_or_cookie_token(request)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
        identity = manager.verify_token(token)
        if required:
            authorized = (
                required.issubset(identity.roles)
                if match_all
                else bool(required & identity.roles)
            )
            if not authorized:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Required role(s): {', '.join(sorted(required))}.",
                )
        return identity

    return _dependency


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
        identity = manager.authenticate_user(
            payload.username, payload.password.get_secret_value()
        )
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

    @router.post(
        "/rotate-password",
        summary="Verify existing credential and rotate principal password hash",
    )
    def rotate_password(
        payload: RotatePasswordRequest,
        request: Request,
        manager: Annotated[DashboardAuthManager, Depends(get_auth_manager)],
    ) -> dict[str, str]:
        enforce_https_transport(request)
        updated = manager.rotate_password(
            payload.username,
            payload.current_secret,
            payload.new_secret,
        )
        return {"status": "rotated", "principal_id": updated.principal_id}

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

    @router.get(
        "/principals",
        response_model=list[PrincipalSummaryResponse],
        summary="List RBAC principals (admin only)",
    )
    def list_principals(
        _identity: Annotated[Identity, Depends(require_roles("admin"))],
        manager: Annotated[DashboardAuthManager, Depends(get_auth_manager)],
    ) -> list[PrincipalSummaryResponse]:
        return [
            PrincipalSummaryResponse(
                principal_id=p.principal_id,
                roles=sorted(p.roles),
                permissions=sorted(p.permissions),
                is_active=p.is_active,
            )
            for p in manager.rbac_store.list_principals()
        ]

    @router.post(
        "/principals",
        response_model=PrincipalSummaryResponse,
        summary="Create or update an RBAC principal using a pre-derived hash (admin only)",
    )
    def upsert_principal(
        payload: PrincipalUpsertRequest,
        _identity: Annotated[Identity, Depends(require_roles("admin"))],
        manager: Annotated[DashboardAuthManager, Depends(get_auth_manager)],
    ) -> PrincipalSummaryResponse:
        principal = RbacPrincipal(
            principal_id=payload.principal_id.strip(),
            hashed_secret=payload.hashed_secret,
            roles=frozenset(payload.roles) if payload.roles else frozenset({"guest"}),
            permissions=frozenset(payload.permissions),
            is_active=payload.is_active,
        )
        manager.rbac_store.upsert_principal(principal)
        return PrincipalSummaryResponse(
            principal_id=principal.principal_id,
            roles=sorted(principal.roles),
            permissions=sorted(principal.permissions),
            is_active=principal.is_active,
        )

    @router.delete(
        "/principals/{principal_id}",
        summary="Delete an RBAC principal (admin only)",
    )
    def delete_principal(
        principal_id: str,
        _identity: Annotated[Identity, Depends(require_roles("admin"))],
        manager: Annotated[DashboardAuthManager, Depends(get_auth_manager)],
    ) -> dict[str, Any]:
        deleted = manager.rbac_store.delete_principal(principal_id)
        return {"deleted": deleted, "principal_id": principal_id}

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
    "PrincipalSummaryResponse",
    "PrincipalUpsertRequest",
    "require_roles",
    "RotatePasswordRequest",
    "SESSION_COOKIE_NAME",
]
