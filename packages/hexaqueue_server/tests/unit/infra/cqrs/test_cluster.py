"""Unit tests for cluster statistics, fair-share, DLQ, and collateral CQRS handlers."""

from typing import Any

from hexaqueue_core.domain.cqrs import (
    GetDeadLetterQueueQuery,
    GetFairShareTreeQuery,
    GetQueueStatsQuery,
    RegisterCollateralCommand,
    SettleBudgetCommand,
)


def test_collateral_and_budget_commands(
    hermetic_cqrs_pipeline: tuple[Any, Any],
) -> None:
    """Verify RegisterCollateral and SettleBudget handlers."""
    _, pipeline = hermetic_cqrs_pipeline
    col_bundle = pipeline.execute(
        RegisterCollateralCommand(
            name="model.pt",
            checksum_sha256="a" * 64,
            size_bytes=4096,
        )
    )
    assert col_bundle.filename == "model.pt"
    assert col_bundle.sha256_checksum == "a" * 64

    # Short checksum triggering zfill(64)
    col_short = pipeline.execute(
        RegisterCollateralCommand(
            name="weights.bin",
            checksum_sha256="abc",
            size_bytes=1024,
        )
    )
    assert len(col_short.sha256_checksum) == 64
    assert col_short.sha256_checksum == "abc".zfill(64)

    budget_res = pipeline.execute(
        SettleBudgetCommand(project_id="proj-hpc", amount_cents=1500)
    )
    assert budget_res["status"] == "SETTLED"
    assert budget_res["settled_amount_cents"] == 1500


def test_cluster_stats_fairshare_and_dlq_queries(
    hermetic_cqrs_pipeline: tuple[Any, Any],
) -> None:
    """Verify queue stats, fairshare tree, and dead letter queue queries."""
    _, pipeline = hermetic_cqrs_pipeline

    # Queue stats
    stats = pipeline.execute(GetQueueStatsQuery())
    assert stats.active_workers >= 1
    assert stats.running_jobs == 0
    assert stats.blocked_jobs == 0

    # Fair-share tree
    tree = pipeline.execute(
        GetFairShareTreeQuery(requesting_user="alice", is_admin=True)
    )
    assert tree.root.id == "root"

    # DLQ query
    dlq_report = pipeline.execute(GetDeadLetterQueueQuery(limit=10))
    assert dlq_report.total_count == 0


def test_collateral_lifecycle_cqrs_handlers(
    hermetic_cqrs_pipeline: tuple[Any, Any],
) -> None:
    """Verify GetCollateralBundle, PinCollateral, UnpinCollateral, and EvictExpired handlers."""
    from hexaqueue_core.domain.cqrs import (
        EvictExpiredCollateralCommand,
        FindCollateralByChecksumQuery,
        GetCollateralBundleQuery,
        PinCollateralCommand,
        UnpinCollateralCommand,
    )

    _, pipeline = hermetic_cqrs_pipeline

    checksum = "b" * 64
    reg_cmd = RegisterCollateralCommand(
        name="dataset.tar.gz",
        checksum_sha256=checksum,
        size_bytes=8192,
    )
    bundle = pipeline.execute(reg_cmd)
    bundle_id = bundle.id

    # 1. Get bundle
    fetched = pipeline.execute(GetCollateralBundleQuery(collateral_id=bundle_id))
    assert fetched.id == bundle_id
    assert fetched.filename == "dataset.tar.gz"

    # 2. Find by checksum (registered, not approved yet -> None)
    found_unapproved = pipeline.execute(
        FindCollateralByChecksumQuery(sha256_checksum=checksum)
    )
    assert found_unapproved is None

    # 3. Pin bundle
    pinned = pipeline.execute(PinCollateralCommand(collateral_id=bundle_id))
    assert pinned.active_pin_count == 1

    # 4. Unpin bundle
    unpinned = pipeline.execute(UnpinCollateralCommand(collateral_id=bundle_id))
    assert unpinned.active_pin_count == 0

    # 5. Evict expired
    evicted = pipeline.execute(
        EvictExpiredCollateralCommand(max_age_seconds=10, high_watermark_bytes=1000)
    )
    assert isinstance(evicted, list)
