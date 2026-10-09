"""Tests for cluster queue stats, fair-share hierarchy, DLQ, and accounting endpoints."""

from fastapi.testclient import TestClient


def test_cluster_fairshare_stats_and_dlq(hermetic_api_client: TestClient) -> None:
    """Verify cluster fair-share tree, aggregate queue statistics, and DLQ query."""
    client = hermetic_api_client

    # 1. Fair-share hierarchy
    resp_fs = client.get("/v1/fairshare", headers={"X-Hexaqueue-User": "alice"})
    fs_code = resp_fs.status_code
    assert fs_code == 200
    assert "root" in resp_fs.json()

    # 2. Cluster stats
    resp_stats = client.get("/v1/stats", headers={"X-Hexaqueue-User": "alice"})
    stats_code = resp_stats.status_code
    assert stats_code == 200
    stats_data = resp_stats.json()
    assert "total_jobs" in stats_data
    assert "active_workers" in stats_data

    # 3. DLQ records
    resp_dlq = client.get("/v1/dlq?limit=20", headers={"X-Hexaqueue-User": "operator"})
    dlq_code = resp_dlq.status_code
    assert dlq_code == 200
    dlq_data = resp_dlq.json()
    assert "records" in dlq_data
    assert dlq_data["total_count"] == 0


def test_cluster_collateral_and_budget(hermetic_api_client: TestClient) -> None:
    """Verify collateral bundle upload staging and budget settlement endpoints."""
    client = hermetic_api_client

    # 1. Collateral upload
    col_payload = {
        "name": "model_weights.bin",
        "checksum_sha256": "a" * 64,
        "size_bytes": 1024 * 1024,
        "tier": "PERMANENT",
        "kind": "BUNDLE",
    }
    resp_col = client.post(
        "/v1/collateral/upload",
        json=col_payload,
        headers={"X-Hexaqueue-User": "alice"},
    )
    col_code = resp_col.status_code
    assert col_code == 200
    col_data = resp_col.json()
    assert col_data["filename"] == "model_weights.bin"
    assert col_data["tier"] == "PERMANENT"

    # 2. Budget settlement
    budget_payload = {
        "project_id": "proj-analytics",
        "amount_cents": 2500,
    }
    resp_budget = client.post(
        "/v1/budget/settle",
        json=budget_payload,
        headers={"X-Hexaqueue-User": "alice"},
    )
    budget_code = resp_budget.status_code
    assert budget_code == 200
    budget_data = resp_budget.json()
    assert budget_data["status"] == "SETTLED"
    assert budget_data["settled_amount_cents"] == 2500
