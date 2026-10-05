"""Unit tests for FairShareNode and FairShareTree domain components."""

import pytest

from hexaqueue_core.domain.fairshare import FairShareNode, FairShareTree


def test_fairshare_node_validation() -> None:
    """Verify FairShareNode validation and domain invariants."""
    node = FairShareNode(id="eng", parent_id="root", shares=2.5)
    res_id = node.id
    assert res_id == "eng"
    res_parent = node.parent_id
    assert res_parent == "root"
    res_shares = node.shares
    assert res_shares == 2.5
    res_usage = node.historical_usage
    assert res_usage == 0.0

    with pytest.raises(ValueError, match="id cannot be empty"):
        FairShareNode(id="   ")

    with pytest.raises(ValueError):
        FairShareNode(id="test", shares=0.0)

    with pytest.raises(ValueError):
        FairShareNode(id="test", historical_usage=-1.0)


def test_fairshare_tree_hierarchy_and_errors() -> None:
    """Verify tree node registration, parent validation, and retrieval."""
    tree = FairShareTree(root_id="cluster-root")
    res_root = tree.root_id
    assert res_root == "cluster-root"

    root_node = tree.get_node("cluster-root")
    assert root_node is not None
    res_shares = root_node.shares
    assert res_shares == 1.0

    # Add child to valid root
    dept = FairShareNode(id="dept-ai", parent_id="cluster-root", shares=3.0)
    tree.add_node(dept)
    res_dept = tree.get_node("dept-ai")
    assert res_dept is not None
    assert res_dept.shares == 3.0

    # Add child to missing parent raises ValueError
    orphan = FairShareNode(id="user-orphan", parent_id="nonexistent-parent")
    with pytest.raises(ValueError, match="does not exist in fair-share tree"):
        tree.add_node(orphan)

    res_missing = tree.get_node("ghost")
    assert res_missing is None


def test_fairshare_tree_usage_propagation() -> None:
    """Verify usage records propagate upward to parents and root."""
    tree = FairShareTree(root_id="root")
    tree.add_node(FairShareNode(id="dept", parent_id="root", shares=2.0))
    tree.add_node(FairShareNode(id="team", parent_id="dept", shares=1.0))
    tree.add_node(FairShareNode(id="alice", parent_id="team", shares=1.0))

    tree.record_usage(node_id="alice", delta_usage=100.0, timestamp=1000.0)

    res_alice = tree.get_node("alice")
    assert res_alice is not None
    assert res_alice.historical_usage == 100.0

    res_team = tree.get_node("team")
    assert res_team is not None
    assert res_team.historical_usage == 100.0

    res_dept = tree.get_node("dept")
    assert res_dept is not None
    assert res_dept.historical_usage == 100.0

    res_root = tree.get_node("root")
    assert res_root is not None
    assert res_root.historical_usage == 100.0

    with pytest.raises(ValueError, match="not found"):
        tree.record_usage("unknown", 50.0, 1000.0)

    with pytest.raises(ValueError, match="cannot be negative"):
        tree.record_usage("alice", -10.0, 1000.0)


def test_fairshare_tree_exponential_decay() -> None:
    """Verify continuous exponential decay over half-life intervals."""
    tree = FairShareTree(root_id="root")
    tree.add_node(FairShareNode(id="user1", parent_id="root", shares=1.0))

    t0 = 10000.0
    tree.record_usage("user1", 1000.0, timestamp=t0)

    # After 1 half-life (604800s = 7 days)
    half_life = 604800.0
    t1 = t0 + half_life
    tree.apply_decay(timestamp=t1, half_life_seconds=half_life)

    node1 = tree.get_node("user1")
    assert node1 is not None
    res_usage_t1 = round(node1.historical_usage, 2)
    assert res_usage_t1 == 500.0

    # After 2nd half-life
    t2 = t1 + half_life
    tree.apply_decay(timestamp=t2, half_life_seconds=half_life)
    res_usage_t2 = round(node1.historical_usage, 2)
    assert res_usage_t2 == 250.0

    with pytest.raises(ValueError, match="must be positive"):
        tree.apply_decay(t2, half_life_seconds=-1.0)


def test_fairshare_normalized_shares_and_factor_calculation() -> None:
    """Verify tree-wide normalized entitlement fractions and factor computation."""
    tree = FairShareTree(root_id="root")
    # Department A: 75% entitlement, Department B: 25% entitlement
    tree.add_node(FairShareNode(id="dept-a", parent_id="root", shares=3.0))
    tree.add_node(FairShareNode(id="dept-b", parent_id="root", shares=1.0))

    # User A1: 50% of Dept A (37.5% total), User A2: 50% of Dept A (37.5% total)
    tree.add_node(FairShareNode(id="alice", parent_id="dept-a", shares=1.0))
    tree.add_node(FairShareNode(id="bob", parent_id="dept-a", shares=1.0))

    # User B1: 100% of Dept B (25% total)
    tree.add_node(FairShareNode(id="carol", parent_id="dept-b", shares=1.0))

    normalized = tree.compute_normalized_shares()
    res_alice_share = normalized["alice"]
    assert res_alice_share == pytest.approx(0.375)
    res_bob_share = normalized["bob"]
    assert res_bob_share == pytest.approx(0.375)
    res_carol_share = normalized["carol"]
    assert res_carol_share == pytest.approx(0.25)

    # Initial factors: 0 usage -> maximum factor 1.0
    res_alice_factor = tree.compute_fairshare_factor("alice", 1000.0)
    assert res_alice_factor == 1.0

    # Unknown user gets 1.0
    res_unknown = tree.compute_fairshare_factor("unknown", 1000.0)
    assert res_unknown == 1.0

    # Alice and Carol consume usage
    # Total root usage: 1000. Alice consumed 375 (37.5% of total, exact target share)
    # Carol consumed 500 (50% of total, 2x target share)
    tree.record_usage("alice", 375.0, 1000.0)
    tree.record_usage("carol", 500.0, 1000.0)

    # Alice: actual_usage_fraction = 375 / 875 = 0.4285...
    # Exact check when actual fraction equals target fraction:
    # Set Bob to 375 and Carol to 250 -> total 1000.
    tree_exact = FairShareTree(root_id="root")
    tree_exact.add_node(FairShareNode(id="u1", parent_id="root", shares=1.0))
    tree_exact.add_node(FairShareNode(id="u2", parent_id="root", shares=1.0))
    # Each user target share is 0.5.
    tree_exact.record_usage("u1", 50.0, 1000.0)
    tree_exact.record_usage("u2", 50.0, 1000.0)

    # Both u1 and u2 have actual share 50/100 = 0.5. ratio = 0.5 / 0.5 = 1.0 -> 2^(-1) = 0.5
    factor_u1 = tree_exact.compute_fairshare_factor("u1", 1000.0)
    assert factor_u1 == pytest.approx(0.5)

    # Now u1 consumes 100 more -> u1=150, u2=50, total=200.
    # u1 actual fraction = 150/200 = 0.75. ratio = 0.75 / 0.5 = 1.5 -> 2^(-1.5) = 0.3535...
    # u2 actual fraction = 50/200 = 0.25. ratio = 0.25 / 0.5 = 0.5 -> 2^(-0.5) = 0.7071...
    tree_exact.record_usage("u1", 100.0, 1000.0)
    factor_u1_over = tree_exact.compute_fairshare_factor("u1", 1000.0)
    factor_u2_under = tree_exact.compute_fairshare_factor("u2", 1000.0)

    assert factor_u2_under > factor_u1_over
    assert factor_u2_under == pytest.approx(0.7071, rel=1e-3)
    assert factor_u1_over == pytest.approx(0.3535, rel=1e-3)
