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

    # 3. Reservation settlement with tenant ownership verification
    resp_res = client.post(
        "/v1/budget/reserve",
        json={
            "tenant_id": "tenant-cluster-api",
            "job_id": "job-api-res-1",
            "estimated_credits": 100.0,
        },
        headers={"X-Hexaqueue-User": "alice"},
    )
    res_code = resp_res.status_code
    assert res_code == 200
    res_id = resp_res.json()["reservation_id"]

    # Unauthorized settlement by mismatched tenant fails
    resp_unauth = client.post(
        "/v1/budget/settle",
        json={
            "project_id": "tenant-intruder",
            "reservation_id": res_id,
            "actual_credits": 40.0,
        },
        headers={"X-Hexaqueue-User": "bob"},
    )
    unauth_code = resp_unauth.status_code
    assert unauth_code == 400

    # Authorized settlement succeeds
    resp_auth = client.post(
        "/v1/budget/settle",
        json={
            "project_id": "tenant-cluster-api",
            "reservation_id": res_id,
            "actual_credits": 40.0,
        },
        headers={"X-Hexaqueue-User": "alice"},
    )
    auth_code = resp_auth.status_code
    assert auth_code == 200
    auth_status = resp_auth.json()["status"]
    assert auth_status == "SETTLED"


def test_cluster_collateral_endpoints(hermetic_api_client: TestClient) -> None:
    """Verify collateral metadata inspection, pin, unpin, checksum lookup, and evict endpoints."""
    client = hermetic_api_client

    sha256 = "c" * 64
    reg_resp = client.post(
        "/v1/collateral/upload",
        json={
            "name": "data.tar",
            "checksum_sha256": sha256,
            "size_bytes": 2048,
            "tier": "TEMPORARY",
            "ttl_seconds": 60,
        },
        headers={"X-Hexaqueue-User": "bob"},
    )
    reg_code = reg_resp.status_code
    assert reg_code == 200
    col_id = reg_resp.json()["id"]

    # 1. Get by ID
    get_resp = client.get(
        f"/v1/collateral/{col_id}",
        headers={"X-Hexaqueue-User": "bob"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["filename"] == "data.tar"
    assert get_resp.json()["ttl_seconds"] == 60

    # 2. Checksum lookup (unapproved -> null)
    chk_resp = client.get(
        f"/v1/collateral/checksum/{sha256}",
        headers={"X-Hexaqueue-User": "bob"},
    )
    assert chk_resp.status_code == 200
    assert chk_resp.json() is None

    # 3. Pin collateral
    pin_resp = client.post(
        f"/v1/collateral/{col_id}/pin",
        headers={"X-Hexaqueue-User": "bob"},
    )
    assert pin_resp.status_code == 200
    assert pin_resp.json()["active_pin_count"] == 1

    # 4. Unpin collateral
    unpin_resp = client.post(
        f"/v1/collateral/{col_id}/unpin",
        headers={"X-Hexaqueue-User": "bob"},
    )
    assert unpin_resp.status_code == 200
    assert unpin_resp.json()["active_pin_count"] == 0

    # 5. Evict collateral
    evict_resp = client.post(
        "/v1/collateral/evict",
        json={"max_age_seconds": 3600},
        headers={"X-Hexaqueue-User": "operator", "X-Hexaqueue-Role": "admin"},
    )
    assert evict_resp.status_code == 200
    assert isinstance(evict_resp.json(), list)
