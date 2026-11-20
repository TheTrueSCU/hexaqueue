"""Unit tests for cluster statistics, fair-share, DLQ, and collateral CQRS handlers."""

from typing import Any

import pytest

from hexaqueue_core.domain.collateral import CollateralTier
from hexaqueue_core.domain.cqrs import (
    DeleteCollateralCommand,
    GetDeadLetterQueueQuery,
    GetFairShareTreeQuery,
    GetQueueStatsQuery,
    ListCollateralQuery,
    PromoteCollateralCommand,
    RegisterCollateralCommand,
    SettleBudgetCommand,
    SubmitRunCommand,
)
from hexaqueue_core.domain.exceptions import HexaqueueError, PermissionDeniedError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.run import RunSpec


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
    assert stats.active_workers == 0
    assert stats.running_jobs == 0
    assert stats.blocked_jobs == 0

    # Fair-share tree
    tree = pipeline.execute(
        GetFairShareTreeQuery(requesting_user="alice", is_admin=True)
    )
    assert tree.root.id == "root"
    child_ids = [child.id for child in tree.root.children]
    assert "default" in child_ids

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


def test_fairshare_tree_includes_active_job_owners(
    hermetic_cqrs_pipeline: tuple[Any, Any],
) -> None:
    """Verify FairShareTree includes default and distinct job owners from jobs."""
    from hexaqueue_core.domain.cqrs import SubmitRunCommand
    from hexaqueue_core.domain.job import JobSpec
    from hexaqueue_core.domain.run import RunSpec

    _, pipeline = hermetic_cqrs_pipeline
    job = JobSpec(
        id="fs-job-1",
        run_id="fs-run-1",
        name="fs-job",
        command="echo hi",
        owner="rjdw",
        user="rjdw",
    )
    run = RunSpec(id="fs-run-1", name="fs-test", owner="rjdw")
    _submitted = pipeline.execute(
        SubmitRunCommand(run_spec=run, jobs=[job], user_id="rjdw")
    )
    assert _submitted.run_id == "fs-run-1"

    tree = pipeline.execute(
        GetFairShareTreeQuery(requesting_user="rjdw", is_admin=True)
    )
    children_by_id = {child.id: child for child in tree.root.children}
    assert "default" in children_by_id
    assert "rjdw" in children_by_id
    assert children_by_id["rjdw"].raw_usage >= 1.0


def test_list_promote_and_delete_collateral_rbac_and_guards(
    hermetic_cqrs_pipeline: tuple[Any, Any],
) -> None:
    """Verify ListCollateralQuery RBAC, PromoteCollateral elevation, and DeleteCollateral guards."""
    _, pipeline = hermetic_cqrs_pipeline

    b_alice = pipeline.execute(
        RegisterCollateralCommand(
            name="alice-temp.bin",
            checksum_sha256="c" * 64,
            size_bytes=1024,
            user_id="alice",
        )
    )
    b_bob = pipeline.execute(
        RegisterCollateralCommand(
            name="bob-temp.bin",
            checksum_sha256="d" * 64,
            size_bytes=2048,
            user_id="bob",
        )
    )

    alice_list = pipeline.execute(ListCollateralQuery(user_id="alice", elevate=False))
    alice_ids = [b.id for b in alice_list]
    assert alice_ids == [b_alice.id]

    admin_list = pipeline.execute(ListCollateralQuery(user_id="admin", elevate=True))
    admin_ids = {b.id for b in admin_list}
    assert {b_alice.id, b_bob.id} <= admin_ids

    # Non-admin cannot promote
    with pytest.raises(PermissionDeniedError):
        pipeline.execute(
            PromoteCollateralCommand(
                collateral_id=b_alice.id, user_id="alice", elevate=False
            )
        )

    promoted = pipeline.execute(
        PromoteCollateralCommand(
            collateral_id=b_alice.id, user_id="admin", elevate=True
        )
    )
    assert promoted.tier == CollateralTier.PERMANENT

    # Non-admin cannot delete PERMANENT collateral even if they own it
    with pytest.raises(PermissionDeniedError):
        pipeline.execute(
            DeleteCollateralCommand(
                collateral_id=b_alice.id, user_id="alice", elevate=False
            )
        )

    # Non-admin cannot delete another owner's collateral
    with pytest.raises(PermissionDeniedError):
        pipeline.execute(
            DeleteCollateralCommand(
                collateral_id=b_bob.id, user_id="alice", elevate=False
            )
        )

    # Active-job guard blocks deleting collateral referenced by a non-terminal job
    active_job = JobSpec(
        id="job-uses-bob",
        run_id="run-uses-bob",
        name="use-bob",
        command="echo ok",
        owner="bob",
        user="bob",
        collateral_ids=[b_bob.id],
    )
    pipeline.execute(
        SubmitRunCommand(
            run_spec=RunSpec(id="run-uses-bob", name="bob-run", owner="bob"),
            jobs=[active_job],
            user_id="bob",
        )
    )
    with pytest.raises(HexaqueueError, match="referenced by active job"):
        pipeline.execute(
            DeleteCollateralCommand(
                collateral_id=b_bob.id, user_id="bob", elevate=False
            )
        )

    # Unused permanent bundle can be deleted by admin
    deleted = pipeline.execute(
        DeleteCollateralCommand(collateral_id=b_alice.id, user_id="admin", elevate=True)
    )
    assert deleted == b_alice.id
