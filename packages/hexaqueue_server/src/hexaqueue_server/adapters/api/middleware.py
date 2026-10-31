"""Zero-trust security boundary middleware and access logging for Hexaqueue Server.

Notes/Architectural Intent:
    Intercepts inbound REST requests to enforce CNCF SPIFFE/SPIRE workload identity
    attestation, evaluate boundary authorization policies, and emit structured SIEM
    audit log entries for every boundary traversal.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from hexaqueue_core.domain.security import BoundaryAuditRecord

if TYPE_CHECKING:
    from hexaqueue_core.ports.security import (
        BoundaryAuditLoggerPort,
        SpiffeAuthorizerPort,
        WorkloadIdentityPort,
    )


class ZeroTrustBoundaryMiddleware(BaseHTTPMiddleware):
    """Zero-trust perimeter enforcement and boundary audit logging middleware.

    Notes/Architectural Intent:
        Extracts caller SPIFFE identities from request headers or TLS client certificates,
        evaluates caller permissions against SpiffeAuthorizerPort, and emits immutable
        structured audit records to BoundaryAuditLoggerPort.
    """

    def _extract_caller_spiffe(self, request: Request) -> str | None:
        """Extract caller SPIFFE identity from request headers or bearer token.

        Args:
            request: Inbound FastAPI/Starlette Request instance.

        Returns:
            Extracted SPIFFE ID string, or None if missing or invalid.
        """
        raw_spiffe = request.headers.get("x-spiffe-id")
        if raw_spiffe:
            return raw_spiffe.strip()

        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            workload_port: WorkloadIdentityPort | None = getattr(
                request.app.state, "workload_identity", None
            )
            if workload_port is not None:
                try:
                    svid = workload_port.validate_jwt_svid(
                        token=token, audience={"hexaqueue", "server"}
                    )
                    return svid.uri
                except Exception:
                    return None
        return None

    async def _emit_audit(
        self,
        audit_logger: BoundaryAuditLoggerPort | None,
        *,
        action: str,
        verdict: str,
        caller_spiffe: str | None,
        client_ip: str | None,
        duration_ms: float,
        status_code: int,
        boundary: str,
        resource_id: str,
    ) -> None:
        """Emit a structured SIEM boundary audit record if logger is configured.

        Args:
            audit_logger: Optional BoundaryAuditLoggerPort adapter.
            action: HTTP method / action name.
            verdict: Authorization verdict ('ALLOWED' or 'DENIED').
            caller_spiffe: Caller SPIFFE ID or None.
            client_ip: Remote IP address.
            duration_ms: Processing duration in milliseconds.
            status_code: HTTP response status code.
            boundary: Target API boundary string.
            resource_id: Target resource or URL path.
        """
        if audit_logger is None:
            return
        record = BoundaryAuditRecord(
            action=action,
            audit_id=str(uuid4()),
            authorization_verdict=verdict,
            caller_spiffe_id=caller_spiffe,
            client_ip=client_ip,
            duration_ms=duration_ms,
            status_code=status_code,
            target_boundary=boundary,
            target_resource_id=resource_id,
        )
        await audit_logger.log_access(record)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process an inbound request through zero-trust security checks and audit logging.

        Args:
            request: Inbound FastAPI/Starlette Request instance.
            call_next: Downstream ASGI application endpoint.

        Returns:
            HTTP Response.
        """
        start_time = time.monotonic()
        client_ip = request.client.host if request.client else None
        boundary = f"rest:{request.method.lower()}:{request.url.path}"
        caller_spiffe = self._extract_caller_spiffe(request)

        server_cfg = getattr(request.app.state, "server_config", None)
        security_cfg = getattr(server_cfg, "security", None) if server_cfg else None
        authorizer: SpiffeAuthorizerPort | None = getattr(
            request.app.state, "spiffe_authorizer", None
        )
        audit_logger: BoundaryAuditLoggerPort | None = getattr(
            request.app.state, "audit_logger", None
        )

        spiffe_enabled = bool(security_cfg and security_cfg.spiffe_enabled)
        audit_enabled = bool(security_cfg is None or security_cfg.audit_enabled)

        # Evaluate boundary authorization if enabled
        if spiffe_enabled and authorizer is not None:
            is_authorized = await authorizer.authorize(
                spiffe_id=caller_spiffe,
                boundary=boundary,
                action=request.method,
            )
            if not is_authorized:
                duration_ms = (time.monotonic() - start_time) * 1000.0
                status_code = 401 if caller_spiffe is None else 403

                if audit_enabled:
                    await self._emit_audit(
                        audit_logger,
                        action=request.method,
                        verdict="DENIED",
                        caller_spiffe=caller_spiffe,
                        client_ip=client_ip,
                        duration_ms=duration_ms,
                        status_code=status_code,
                        boundary=boundary,
                        resource_id=request.url.path,
                    )

                error_msg = (
                    "Unauthenticated caller: SPIFFE identity required."
                    if caller_spiffe is None
                    else f"Caller SPIFFE identity '{caller_spiffe}' is not authorized for '{boundary}'."
                )
                return JSONResponse(
                    status_code=status_code,
                    content={"detail": error_msg},
                )

        # Downstream request execution
        response = await call_next(request)
        duration_ms = (time.monotonic() - start_time) * 1000.0

        if audit_enabled:
            await self._emit_audit(
                audit_logger,
                action=request.method,
                verdict="ALLOWED",
                caller_spiffe=caller_spiffe,
                client_ip=client_ip,
                duration_ms=duration_ms,
                status_code=response.status_code,
                boundary=boundary,
                resource_id=request.url.path,
            )

        return response
