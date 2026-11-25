"""HTTP remote collateral adapter for distributed Hexaqueue clients.

Notes/Architectural Intent:
    Implements CollateralServicePort over HTTP against a separately running
    hexaqueue-server process so standalone dashboard (`:8080`) and CLI clients
    can inspect, stream-stage, promote, pin, unpin, and delete collateral managed by `:8000`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, BinaryIO

import httpx
from pydantic import SecretStr

from hexaqueue_collateral.domain.models import IngestionRequest, StagedUploadDescriptor
from hexaqueue_collateral.ports.service import CollateralServicePort
from hexaqueue_core.domain.collateral import CollateralBundle
from hexaqueue_core.domain.exceptions import HexaqueueError


class HttpCollateralServiceAdapter(CollateralServicePort):
    """Remote HTTP client adapter implementing CollateralServicePort.

    Args:
        base_url: Base URL of the central ``hexaqueue-server`` process.
        admin_token: Optional bearer token for elevated administrative requests.
        user_id: Default acting user identity forwarded via ``X-Hexaqueue-User``.
        elevate: Default privilege elevation flag forwarded via ``X-Hexaqueue-Elevate``.
        timeout: HTTP request timeout in seconds.
        transport: Optional custom ``httpx.AsyncBaseTransport`` for hermetic testing.

    Notes/Architectural Intent:
        Delegates collateral listing, stream staging, promotion, pinning, and
        deletion to ``/v1/collateral*`` endpoints using ``httpx.AsyncClient`` while
        forwarding both ``Authorization: Bearer`` and ``X-Hexaqueue-*`` headers.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        admin_token: SecretStr | None = None,
        user_id: str = "default",
        elevate: bool = False,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._admin_token = admin_token
        self._user_id = user_id
        self._elevate = elevate
        self._timeout = timeout
        self._transport = transport
        self._auth_ctx: ContextVar[tuple[str, bool] | None] = ContextVar(
            f"http_collateral_auth_{id(self)}", default=None
        )

    @contextmanager
    def acting_as(self, user_id: str, elevate: bool) -> Generator[None]:
        """Temporarily bind per-task caller identity headers for outbound HTTP calls.

        Args:
            user_id: Acting user identity for ``X-Hexaqueue-User``.
            elevate: Administrative elevation flag for ``X-Hexaqueue-Elevate``.

        Yields:
            None while the task-local ContextVar override is active.

        Notes/Architectural Intent:
            Preserves coroutine-safe per-command identity propagation when shared
            across concurrent CLI or dashboard operations.
        """
        token = self._auth_ctx.set((user_id, elevate))
        try:
            yield
        finally:
            self._auth_ctx.reset(token)

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        override = self._auth_ctx.get()
        uid, is_elevated = (
            override if override is not None else (self._user_id, self._elevate)
        )
        headers: dict[str, str] = {
            "X-Hexaqueue-User": uid,
            "X-Hexaqueue-Elevate": "true" if is_elevated else "false",
        }
        if self._admin_token is not None:
            token_val = self._admin_token.get_secret_value()
            headers["Authorization"] = f"Bearer {token_val}"
            headers["X-Hexaqueue-Admin-Token"] = token_val
        if extra:
            headers.update(extra)
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        content: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.request(
                    method,
                    url,
                    json=json,
                    content=content,
                    headers=self._headers(extra_headers),
                )
        except httpx.HTTPError as exc:
            msg = f"Remote collateral error contacting {url}: {exc}"
            raise HexaqueueError(msg) from exc

        if response.status_code >= 400:
            detail = response.text
            try:
                body = response.json()
                if isinstance(body, dict) and "detail" in body:
                    detail = str(body["detail"])
            except Exception:  # noqa: BLE001
                pass
            msg = f"Remote collateral error ({response.status_code}): {detail}"
            raise HexaqueueError(msg)
        if not response.content:
            return None
        return response.json()

    async def register(self, request: IngestionRequest) -> StagedUploadDescriptor:
        """Register a collateral bundle via the remote controller API.

        Args:
            request: Collateral ingestion registration metadata.

        Returns:
            StagedUploadDescriptor with remote bundle metadata and staging URI.

        Raises:
            HexaqueueError: If registration fails on the remote controller.
        """
        payload = {
            "name": request.filename,
            "checksum_sha256": request.sha256_checksum,
            "size_bytes": request.size_bytes,
            "tier": request.tier.value,
            "kind": request.kind.value,
            "ttl_seconds": request.ttl_seconds,
        }
        data = await self._request("POST", "/v1/collateral/upload", json=payload)
        bundle = CollateralBundle.model_validate(data)
        return StagedUploadDescriptor(
            bundle=bundle,
            staging_path=bundle.staging_uri,
            upload_url=bundle.staging_uri,
        )

    async def stage_file(
        self,
        collateral_id: str,
        source: bytes | BinaryIO | Path | str,
    ) -> CollateralBundle:
        """Reject unsupported raw byte staging via the legacy two-step JSON interface.

        Args:
            collateral_id: Registered bundle identifier.
            source: Unused payload source.

        Raises:
            HexaqueueError: Always raised; use ``stage_stream`` for remote uploads.

        Notes/Architectural Intent:
            Preserved so ``CollateralServicePort`` callers explicitly distinguish
            JSON metadata registration from ``/v1/collateral/stage`` binary streaming.
        """
        msg = f"Direct byte staging for {collateral_id} is not supported over remote JSON API"
        raise HexaqueueError(msg)

    async def stage_stream(
        self,
        filename: str,
        content: bytes,
        sha256_checksum: str | None = None,
    ) -> CollateralBundle:
        """Stream raw binary collateral payload directly into remote CAS storage.

        Args:
            filename: Logical collateral filename for ``X-Collateral-Name``.
            content: Raw binary bytes to upload.
            sha256_checksum: Optional precomputed SHA-256 hex digest.

        Returns:
            Verified and approved CollateralBundle returned by ``POST /v1/collateral/stage``.

        Raises:
            HexaqueueError: If upload fails or checksum verification rejects the payload.
        """
        digest = sha256_checksum or hashlib.sha256(content).hexdigest()
        data = await self._request(
            "POST",
            "/v1/collateral/stage",
            content=content,
            extra_headers={
                "X-Collateral-Name": filename,
                "X-Collateral-Sha256": digest,
                "Content-Type": "application/octet-stream",
            },
        )
        return CollateralBundle.model_validate(data)

    async def process_quarantine(self, collateral_id: str) -> CollateralBundle:
        """Retrieve current bundle metadata from the remote controller.

        Args:
            collateral_id: Target collateral bundle identifier.

        Returns:
            Validated CollateralBundle from remote controller.
        """
        return await self.get_bundle(collateral_id)

    async def get_bundle(self, collateral_id: str) -> CollateralBundle:
        """Retrieve a single CollateralBundle by ID.

        Args:
            collateral_id: Target collateral bundle identifier.

        Returns:
            CollateralBundle instance.

        Raises:
            HexaqueueError: If retrieval fails.
        """
        data = await self._request("GET", f"/v1/collateral/{collateral_id}")
        return CollateralBundle.model_validate(data)

    async def find_by_checksum(self, sha256_checksum: str) -> CollateralBundle | None:
        """Find an approved bundle by SHA-256 checksum.

        Args:
            sha256_checksum: 64-character SHA-256 hex digest.

        Returns:
            Matching CollateralBundle or None when not present.
        """
        data = await self._request("GET", f"/v1/collateral/checksum/{sha256_checksum}")
        return CollateralBundle.model_validate(data) if data is not None else None

    async def get_download_url(self, collateral_id: str) -> str:
        """Retrieve a verified download URL for an approved bundle.

        Args:
            collateral_id: Target collateral bundle identifier.

        Returns:
            Preauthenticated download URL string.
        """
        data = await self._request("GET", f"/v1/collateral/{collateral_id}/download")
        return str(data["download_url"])

    async def pin_bundle(self, collateral_id: str) -> CollateralBundle:
        """Pin a collateral bundle against eviction.

        Args:
            collateral_id: Target collateral bundle identifier.

        Returns:
            Updated CollateralBundle.
        """
        data = await self._request("POST", f"/v1/collateral/{collateral_id}/pin")
        return CollateralBundle.model_validate(data)

    async def unpin_bundle(self, collateral_id: str) -> CollateralBundle:
        """Unpin a collateral bundle.

        Args:
            collateral_id: Target collateral bundle identifier.

        Returns:
            Updated CollateralBundle.
        """
        data = await self._request("POST", f"/v1/collateral/{collateral_id}/unpin")
        return CollateralBundle.model_validate(data)

    async def evict_expired(
        self,
        max_age_seconds: int | None = None,
        high_watermark_bytes: int | None = None,
    ) -> list[str]:
        """Trigger garbage collection eviction on the remote controller.

        Args:
            max_age_seconds: Optional maximum TTL override in seconds.
            high_watermark_bytes: Optional capacity ceiling override in bytes.

        Returns:
            List of evicted bundle identifiers.
        """
        payload = {
            "max_age_seconds": max_age_seconds,
            "high_watermark_bytes": high_watermark_bytes,
        }
        data = await self._request("POST", "/v1/collateral/evict", json=payload)
        return [str(item) for item in data]

    async def list_bundles(self) -> list[CollateralBundle]:
        """List all collateral bundles from the remote controller.

        Returns:
            List of CollateralBundle records visible to the caller.
        """
        data = await self._request("GET", "/v1/collateral")
        return [CollateralBundle.model_validate(item) for item in data]

    async def promote_bundle(self, collateral_id: str) -> CollateralBundle:
        """Promote a TEMPORARY bundle to PERMANENT on the remote controller.

        Args:
            collateral_id: Target collateral bundle identifier.

        Returns:
            Updated CollateralBundle in PERMANENT tier.
        """
        data = await self._request("POST", f"/v1/collateral/{collateral_id}/promote")
        return CollateralBundle.model_validate(data)

    async def delete_bundle(self, collateral_id: str) -> str:
        """Delete an unused collateral bundle on the remote controller.

        Args:
            collateral_id: Target collateral bundle identifier.

        Returns:
            Deleted bundle identifier string.
        """
        data = await self._request("DELETE", f"/v1/collateral/{collateral_id}")
        if isinstance(data, dict) and "deleted_id" in data:
            return str(data["deleted_id"])
        return collateral_id


__all__ = [
    "HttpCollateralServiceAdapter",
]
