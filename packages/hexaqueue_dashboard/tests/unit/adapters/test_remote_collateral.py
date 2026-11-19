"""Unit tests for HttpCollateralServiceAdapter."""

from __future__ import annotations

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
from hexaqueue_dashboard.adapters.remote_collateral import (
    HttpCollateralServiceAdapter,
)


def _sample_bundle(
    bundle_id: str = "col-1",
    tier: CollateralTier = CollateralTier.TEMPORARY,
) -> CollateralBundle:
    return CollateralBundle(
        id=bundle_id,
        job_id="job-1",
        owner="alice",
        filename="weights.bin",
        size_bytes=128,
        sha256_checksum="a" * 64,
        kind=CollateralKind.DATASET,
        tier=tier,
        state=CollateralState.APPROVED,
        staging_uri="/tmp/staging/col-1",
        active_uri="/tmp/active/col-1",
    )


@pytest.mark.asyncio
async def test_http_collateral_list_promote_delete() -> None:
    """Verify list_bundles, promote_bundle, and delete_bundle HTTP calls."""
    temp_bundle = _sample_bundle("col-1", CollateralTier.TEMPORARY)
    perm_bundle = _sample_bundle("col-1", CollateralTier.PERMANENT)

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/v1/collateral/upload":
            return httpx.Response(200, json=temp_bundle.model_dump(mode="json"))
        if request.method == "GET" and path == "/v1/collateral":
            return httpx.Response(200, json=[temp_bundle.model_dump(mode="json")])
        if request.method == "GET" and path == "/v1/collateral/col-1":
            return httpx.Response(200, json=temp_bundle.model_dump(mode="json"))
        if request.method == "GET" and path == f"/v1/collateral/checksum/{'a' * 64}":
            return httpx.Response(200, json=temp_bundle.model_dump(mode="json"))
        if request.method == "GET" and path == "/v1/collateral/col-1/download":
            return httpx.Response(
                200, json={"download_url": "file:///tmp/active/col-1"}
            )
        if request.method == "POST" and path == "/v1/collateral/col-1/pin":
            return httpx.Response(200, json=temp_bundle.model_dump(mode="json"))
        if request.method == "POST" and path == "/v1/collateral/col-1/unpin":
            return httpx.Response(200, json=temp_bundle.model_dump(mode="json"))
        if request.method == "POST" and path == "/v1/collateral/evict":
            return httpx.Response(200, json=["col-1"])
        if request.method == "POST" and path == "/v1/collateral/col-1/promote":
            return httpx.Response(200, json=perm_bundle.model_dump(mode="json"))
        if request.method == "DELETE" and path == "/v1/collateral/col-1":
            return httpx.Response(200, json={"deleted_id": "col-1"})
        return httpx.Response(404, json={"detail": "Not found"})

    adapter = HttpCollateralServiceAdapter(
        base_url="http://127.0.0.1:8000",
        admin_token=SecretStr("secret-token"),
        transport=httpx.MockTransport(_handler),
    )

    desc = await adapter.register(
        IngestionRequest(
            job_id="job-1",
            filename="weights.bin",
            size_bytes=128,
            sha256_checksum="a" * 64,
        )
    )
    assert desc.bundle.id == "col-1"

    with pytest.raises(HexaqueueError, match="not supported"):
        await adapter.stage_file("col-1", b"data")

    quarantined = await adapter.process_quarantine("col-1")
    assert quarantined.id == "col-1"

    by_sum = await adapter.find_by_checksum("a" * 64)
    assert by_sum is not None

    dl_url = await adapter.get_download_url("col-1")
    assert dl_url == "file:///tmp/active/col-1"

    pinned = await adapter.pin_bundle("col-1")
    assert pinned.id == "col-1"

    unpinned = await adapter.unpin_bundle("col-1")
    assert unpinned.id == "col-1"

    evicted = await adapter.evict_expired(max_age_seconds=60)
    assert evicted == ["col-1"]

    listed = await adapter.list_bundles()
    assert len(listed) == 1
    assert listed[0].id == "col-1"

    promoted = await adapter.promote_bundle("col-1")
    assert promoted.tier == CollateralTier.PERMANENT

    deleted_id = await adapter.delete_bundle("col-1")
    assert deleted_id == "col-1"

    with pytest.raises(HexaqueueError, match="404"):
        await adapter.get_bundle("missing")
