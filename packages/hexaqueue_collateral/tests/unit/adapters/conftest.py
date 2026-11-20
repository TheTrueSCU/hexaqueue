"""Shared pytest fixtures for hexaqueue-collateral adapter unit tests."""

from __future__ import annotations

import pytest

from hexaqueue_core.domain.collateral import CollateralBundle


class FakeCollateralMetadataStore:
    """In-memory metadata store test double for collateral persistence tests."""

    def __init__(self) -> None:
        self.records: dict[str, CollateralBundle] = {}

    async def record_collateral(self, bundle: CollateralBundle) -> None:
        """Record or update a collateral bundle in memory."""
        self.records[bundle.id] = bundle

    async def get_collateral(self, collateral_id: str) -> CollateralBundle | None:
        """Return a collateral bundle by ID if present."""
        return self.records.get(collateral_id)

    async def list_collateral(self, limit: int = 1000) -> list[CollateralBundle]:
        """List stored collateral bundles."""
        _ = limit
        return list(self.records.values())

    async def delete_collateral(self, collateral_id: str) -> None:
        """Delete a collateral bundle by ID."""
        self.records.pop(collateral_id, None)


@pytest.fixture
def fake_metadata_store() -> FakeCollateralMetadataStore:
    """Return a fresh FakeCollateralMetadataStore instance."""
    return FakeCollateralMetadataStore()


__all__ = [
    "fake_metadata_store",
    "FakeCollateralMetadataStore",
]
