"""Unit tests for HttpCollateralServiceAdapter HTTP client operations."""

import hashlib

import httpx
import pytest
from pydantic import SecretStr

from hexaqueue_collateral.domain.models import IngestionRequest
from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralState,
    CollateralTier,
)
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_server.adapters.http.collateral import HttpCollateralServiceAdapter


def _bundle(
    collateral_id: str = "col-1",
    tier: CollateralTier = CollateralTier.TEMPORARY,
) -> CollateralBundle:
    return CollateralBundle(
        id=collateral_id,
        job_id="default",
        filename="bundle.tar.gz",
        size_bytes=5,
        sha256_checksum=hashlib.sha256(b"hello").hexdigest(),
        tier=tier,
        kind=CollateralKind.BUNDLE,
        state=CollateralState.APPROVED,
        staging_uri="s3://bucket/bundle.tar.gz",
        active_uri="s3://bucket/cas/bundle.tar.gz",
    )


@pytest.mark.asyncio
async def test_collateral_stage_stream_headers_and_identity() -> None:
    """Verify binary stage_stream and acting_as headers on /v1/collateral/stage."""
    captured: list[tuple[str, str, dict[str, str], bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            (request.method, request.url.path, dict(request.headers), request.content)
        )
        if request.url.path == "/v1/collateral/stage":
            return httpx.Response(
                200, json=_bundle("col-staged").model_dump(mode="json")
            )
        if request.url.path == "/v1/collateral/upload":
            return httpx.Response(200, json=_bundle("col-reg").model_dump(mode="json"))
        if request.url.path == "/v1/collateral":
            return httpx.Response(200, json=[_bundle("col-1").model_dump(mode="json")])
        if request.url.path == "/v1/collateral/col-1/promote":
            return httpx.Response(
                200,
                json=_bundle("col-1", tier=CollateralTier.PERMANENT).model_dump(
                    mode="json"
                ),
            )
        if request.url.path == "/v1/collateral/col-1" and request.method == "DELETE":
            return httpx.Response(200, json={"deleted_id": "col-1"})
        return httpx.Response(404, json={"detail": "missing"})

    adapter = HttpCollateralServiceAdapter(
        base_url="http://controller.local:8000",
        admin_token=SecretStr("adm-tok"),
        user_id="bob",
        elevate=False,
        transport=httpx.MockTransport(handler),
    )

    payload = b"hello"
    digest = hashlib.sha256(payload).hexdigest()
    staged = await adapter.stage_stream("bundle.tar.gz", payload)
    assert staged.id == "col-staged"
    assert captured[0][0] == "POST"
    assert captured[0][1] == "/v1/collateral/stage"
    assert captured[0][2]["x-collateral-name"] == "bundle.tar.gz"
    assert captured[0][2]["x-collateral-sha256"] == digest
    assert captured[0][2]["x-hexaqueue-user"] == "bob"
    assert captured[0][2]["x-hexaqueue-elevate"] == "false"
    assert captured[0][2]["authorization"] == "Bearer adm-tok"
    assert captured[0][2]["x-hexaqueue-admin-token"] == "adm-tok"
    assert captured[0][3] == payload

    with adapter.acting_as("admin-user", True):
        promoted = await adapter.promote_bundle("col-1")
    assert promoted.tier == CollateralTier.PERMANENT
    assert captured[1][2]["x-hexaqueue-user"] == "admin-user"
    assert captured[1][2]["x-hexaqueue-elevate"] == "true"

    listed = await adapter.list_bundles()
    assert len(listed) == 1
    assert listed[0].id == "col-1"
    assert captured[2][2]["x-hexaqueue-user"] == "bob"
    assert captured[2][2]["x-hexaqueue-elevate"] == "false"

    deleted_id = await adapter.delete_bundle("col-1")
    assert deleted_id == "col-1"

    reg = await adapter.register(
        IngestionRequest(
            filename="bundle.tar.gz",
            job_id="bob",
            sha256_checksum=digest,
            size_bytes=len(payload),
        )
    )
    assert reg.bundle.id == "col-reg"


@pytest.mark.asyncio
async def test_collateral_stage_file_and_transport_errors() -> None:
    """Verify legacy stage_file error contract and transport exception translation."""

    def fail_transport(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    adapter = HttpCollateralServiceAdapter(
        transport=httpx.MockTransport(fail_transport)
    )

    with pytest.raises(HexaqueueError, match="not supported"):
        await adapter.stage_file("col-1", b"abc")

    with pytest.raises(HexaqueueError, match="Remote collateral error"):
        await adapter.list_bundles()
