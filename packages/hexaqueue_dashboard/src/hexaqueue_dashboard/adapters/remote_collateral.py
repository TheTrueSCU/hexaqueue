"""HTTP remote collateral adapter for standalone Hexaqueue Dashboard processes.

Notes/Architectural Intent:
    Implements CollateralServicePort over HTTP against a separately running
    hexaqueue-server process so standalone dashboard deployments (`:8080`)
    can inspect, promote, and delete collateral managed by `:8000`.
"""

from __future__ import annotations

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
        timeout: HTTP request timeout in seconds.
        transport: Optional custom ``httpx.AsyncBaseTransport`` for hermetic testing.

    Notes/Architectural Intent:
        Delegates collateral listing, promotion, and deletion to ``/v1/collateral*``
        endpoints using ``httpx.AsyncClient``.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        admin_token: SecretStr | None = None,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._admin_token = admin_token
        self._timeout = timeout
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        if self._admin_token is not None:
            return {"Authorization": f"Bearer {self._admin_token.get_secret_value()}"}
        return {}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            response = await client.request(
                method, url, json=json, headers=self._headers()
            )
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
        """Register a collateral bundle via the remote controller API."""
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
        """Unsupported over JSON control API; use direct presigned upload."""
        msg = f"Direct byte staging for {collateral_id} is not supported over remote JSON API"
        raise HexaqueueError(msg)

    async def process_quarantine(self, collateral_id: str) -> CollateralBundle:
        """Retrieve current bundle metadata from the remote controller."""
        return await self.get_bundle(collateral_id)

    async def get_bundle(self, collateral_id: str) -> CollateralBundle:
        """Retrieve a single CollateralBundle by ID."""
        data = await self._request("GET", f"/v1/collateral/{collateral_id}")
        return CollateralBundle.model_validate(data)

    async def find_by_checksum(self, sha256_checksum: str) -> CollateralBundle | None:
        """Find an approved bundle by SHA-256 checksum."""
        data = await self._request("GET", f"/v1/collateral/checksum/{sha256_checksum}")
        return CollateralBundle.model_validate(data) if data is not None else None

    async def get_download_url(self, collateral_id: str) -> str:
        """Retrieve a verified download URL for an approved bundle."""
        data = await self._request("GET", f"/v1/collateral/{collateral_id}/download")
        return str(data["download_url"])

    async def pin_bundle(self, collateral_id: str) -> CollateralBundle:
        """Pin a collateral bundle against eviction."""
        data = await self._request("POST", f"/v1/collateral/{collateral_id}/pin")
        return CollateralBundle.model_validate(data)

    async def unpin_bundle(self, collateral_id: str) -> CollateralBundle:
        """Unpin a collateral bundle."""
        data = await self._request("POST", f"/v1/collateral/{collateral_id}/unpin")
        return CollateralBundle.model_validate(data)

    async def evict_expired(
        self,
        max_age_seconds: int | None = None,
        high_watermark_bytes: int | None = None,
    ) -> list[str]:
        """Trigger garbage collection eviction on the remote controller."""
        payload = {
            "max_age_seconds": max_age_seconds,
            "high_watermark_bytes": high_watermark_bytes,
        }
        data = await self._request("POST", "/v1/collateral/evict", json=payload)
        return [str(item) for item in data]

    async def list_bundles(self) -> list[CollateralBundle]:
        """List all collateral bundles from the remote controller."""
        data = await self._request("GET", "/v1/collateral")
        return [CollateralBundle.model_validate(item) for item in data]

    async def promote_bundle(self, collateral_id: str) -> CollateralBundle:
        """Promote a TEMPORARY bundle to PERMANENT on the remote controller."""
        data = await self._request("POST", f"/v1/collateral/{collateral_id}/promote")
        return CollateralBundle.model_validate(data)

    async def delete_bundle(self, collateral_id: str) -> str:
        """Delete an unused collateral bundle on the remote controller."""
        data = await self._request("DELETE", f"/v1/collateral/{collateral_id}")
        if isinstance(data, dict) and "deleted_id" in data:
            return str(data["deleted_id"])
        return collateral_id


__all__ = [
    "HttpCollateralServiceAdapter",
]
