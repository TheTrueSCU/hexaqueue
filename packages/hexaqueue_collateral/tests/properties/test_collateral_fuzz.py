"""Property-based fuzz testing for collateral retention tiers and CAS eviction invariants.

Notes/Architectural Intent:
    Mathematically verifies dual-retention tier (PERMANENT vs TEMPORARY) invariants
    and Reference-Counted Content-Addressable Storage (CAS) eviction bounds:
    1. Golden/Permanent collateral (`tier == CollateralTier.PERMANENT`) is strictly immune
       to TTL and LRU high-watermark cache eviction under all storage pressure.
    2. Active pinned bundles (`active_pin_count > 0`) can never be evicted.
    3. Pin counters never underflow below zero (`active_pin_count >= 0`).
    4. Deterministic CAS deduplication returns existing approved bundles for identical SHA-256 digests.
"""

import asyncio
import hashlib
import tempfile

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hexaqueue_collateral.adapters.local import LocalCollateralServiceAdapter
from hexaqueue_collateral.domain.models import IngestionRequest
from hexaqueue_core.adapters.storage.presigned import InMemoryPresignedStorageAdapter
from hexaqueue_core.domain.collateral import (
    CollateralBundle,
    CollateralKind,
    CollateralState,
    CollateralTier,
)
from hexaqueue_core.ports.security import SecurityQuarantinePort


class BenignScanner(SecurityQuarantinePort):
    """Mock security scanner approving clean collateral."""

    async def scan_collateral(
        self, bundle: CollateralBundle
    ) -> tuple[CollateralState, str | None]:
        """Flag bundle as approved."""
        return CollateralState.APPROVED, None


@st.composite
def collateral_payload_strategy(draw: st.DrawFn) -> tuple[str, bytes, str]:
    """Generate arbitrary file names, payloads, and verified SHA-256 digests."""
    filename = (
        draw(
            st.text(
                alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
                min_size=3,
                max_size=12,
            )
        )
        + ".bin"
    )
    content = draw(st.binary(min_size=1, max_size=4096))
    checksum = hashlib.sha256(content).hexdigest()
    return filename, content, checksum


@given(
    payloads=st.lists(collateral_payload_strategy(), min_size=1, max_size=5),
    max_age_seconds=st.integers(min_value=0, max_value=3600),
    high_watermark_bytes=st.integers(min_value=0, max_value=100000),
)
@settings(max_examples=25, deadline=None)
def test_permanent_collateral_immune_to_eviction(
    payloads: list[tuple[str, bytes, str]],
    max_age_seconds: int,
    high_watermark_bytes: int,
) -> None:
    """Verify that PERMANENT tier collateral is never evicted under any cache pressure."""

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            adapter = LocalCollateralServiceAdapter(
                base_dir=tmp_dir, security_port=BenignScanner()
            )
            created_ids: list[str] = []

            for idx, (filename, content, checksum) in enumerate(payloads):
                req = IngestionRequest(
                    filename=filename,
                    job_id=f"job-perm-{idx}",
                    kind=CollateralKind.DATASET,
                    sha256_checksum=checksum,
                    size_bytes=len(content),
                    tier=CollateralTier.PERMANENT,
                )
                desc = await adapter.register(req)
                created_ids.append(desc.collateral_id)
                # Stage file
                await adapter.stage_file(desc.collateral_id, content)
                # Process quarantine to approve
                await adapter.process_quarantine(desc.collateral_id)

            # Evict under arbitrary aggressive pressure (even 0 age / 0 watermark)
            evicted = await adapter.evict_expired(
                max_age_seconds=max_age_seconds,
                high_watermark_bytes=high_watermark_bytes,
            )
            evicted_count = len(evicted)
            assert evicted_count == 0

            # All permanent bundles still exist and are APPROVED
            for cid in created_ids:
                bundle = await adapter.get_bundle(cid)
                tier_val = bundle.tier
                assert tier_val == CollateralTier.PERMANENT
                state_val = bundle.state
                assert state_val == CollateralState.APPROVED

    asyncio.run(_run())


@given(
    payloads=st.lists(collateral_payload_strategy(), min_size=1, max_size=5),
    pins=st.lists(st.integers(min_value=1, max_value=5), min_size=1, max_size=5),
)
@settings(max_examples=25, deadline=None)
def test_active_pinned_temporary_collateral_immune_to_eviction(
    payloads: list[tuple[str, bytes, str]],
    pins: list[int],
) -> None:
    """Verify that TEMPORARY collateral with active_pin_count > 0 is never evicted."""

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            adapter = LocalCollateralServiceAdapter(
                base_dir=tmp_dir, security_port=BenignScanner()
            )
            pinned_cids: list[str] = []

            for idx, (filename, content, checksum) in enumerate(payloads):
                req = IngestionRequest(
                    filename=filename,
                    job_id=f"job-temp-{idx}",
                    kind=CollateralKind.BUNDLE,
                    sha256_checksum=checksum,
                    size_bytes=len(content),
                    tier=CollateralTier.TEMPORARY,
                    ttl_seconds=1,  # Expired immediately
                )
                desc = await adapter.register(req)
                await adapter.stage_file(desc.collateral_id, content)
                await adapter.process_quarantine(desc.collateral_id)

                # Pin bundle N times
                pin_count = pins[idx % len(pins)]
                for _ in range(pin_count):
                    await adapter.pin_bundle(desc.collateral_id)

                pinned_cids.append(desc.collateral_id)

            # Attempt eviction with 0s max_age
            evicted = await adapter.evict_expired(
                max_age_seconds=0, high_watermark_bytes=0
            )
            evicted_count = len(evicted)
            assert evicted_count == 0

            # All pinned bundles still exist
            for cid in pinned_cids:
                bundle = await adapter.get_bundle(cid)
                pin_val = bundle.active_pin_count
                assert pin_val > 0

    asyncio.run(_run())


@given(pin_ops=st.lists(st.sampled_from(["pin", "unpin"]), min_size=5, max_size=30))
@settings(max_examples=25, deadline=None)
def test_pin_unpin_counter_invariants(pin_ops: list[str]) -> None:
    """Verify active_pin_count never underflows below 0 and unpin at 0 raises ValueError."""
    bundle = CollateralBundle(
        id="col-fuzz-pin",
        job_id="job-fuzz",
        filename="test.bin",
        sha256_checksum="a" * 64,
        size_bytes=100,
        staging_uri="file:///tmp/test.bin",
    )

    current = bundle
    expected_count = 0
    for op in pin_ops:
        if op == "pin":
            current = current.pin()
            expected_count += 1
        elif expected_count > 0:
            current = current.unpin()
            expected_count -= 1
        else:
            with pytest.raises(ValueError, match="already 0"):
                current.unpin()

        pin_val = current.active_pin_count
        assert pin_val >= 0
        assert pin_val == expected_count


@given(payload=collateral_payload_strategy())
@settings(max_examples=25, deadline=None)
def test_cas_deduplication_idempotency(payload: tuple[str, bytes, str]) -> None:
    """Verify that multiple ingestions of identical content deduplicate cleanly in CAS."""
    filename, content, checksum = payload

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = InMemoryPresignedStorageAdapter()
            adapter = LocalCollateralServiceAdapter(
                base_dir=tmp_dir,
                storage_port=storage,
                security_port=BenignScanner(),
            )

            req1 = IngestionRequest(
                filename=filename,
                job_id="job-dedup-1",
                kind=CollateralKind.DATASET,
                sha256_checksum=checksum,
                size_bytes=len(content),
                tier=CollateralTier.TEMPORARY,
            )
            desc1 = await adapter.register(req1)
            await adapter.stage_file(desc1.collateral_id, content)
            approved1 = await adapter.process_quarantine(desc1.collateral_id)

            # Second identical registration request
            req2 = IngestionRequest(
                filename=filename,
                job_id="job-dedup-2",
                kind=CollateralKind.DATASET,
                sha256_checksum=checksum,
                size_bytes=len(content),
                tier=CollateralTier.TEMPORARY,
            )
            desc2 = await adapter.register(req2)
            assert desc2.is_cache_hit is True
            assert desc2.bundle.id == approved1.id
            # Find by checksum should resolve to approved1
            found = await adapter.find_by_checksum(checksum)
            assert found is not None
            found_hash = found.sha256_checksum
            assert found_hash == checksum
            found_id = found.id
            assert found_id == approved1.id

    asyncio.run(_run())
