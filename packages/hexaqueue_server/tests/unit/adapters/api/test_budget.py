"""Tests for budget accounting, reservation holds, and cluster health REST endpoints."""

from fastapi.testclient import TestClient


def test_budget_reserve_settle_segment_and_balance_api(
    hermetic_api_client: TestClient,
) -> None:
    """Verify POST /v1/budget/reserve, POST /v1/budget/settle-segment, and GET /v1/budget/tenants/{id}."""
    client = hermetic_api_client

    # 1. Place a reservation hold
    reserve_payload = {
        "tenant_id": "tenant-dev",
        "job_id": "job-api-test-1",
        "estimated_credits": 150.0,
    }
    resp_reserve = client.post(
        "/v1/budget/reserve",
        json=reserve_payload,
        headers={"X-Hexaqueue-User": "alice"},
    )
    res_code = resp_reserve.status_code
    assert res_code == 200
    res_data = resp_reserve.json()
    res_id = res_data["reservation_id"]
    res_status = res_data["status"]
    assert res_status == "RESERVED"
    assert res_id.startswith("hold-")

    # 2. Check tenant balance
    resp_bal = client.get(
        "/v1/budget/tenants/tenant-dev",
        headers={"X-Hexaqueue-User": "alice"},
    )
    bal_code = resp_bal.status_code
    assert bal_code == 200
    bal_data = resp_bal.json()
    avail = bal_data["available_balance"]
    holds = bal_data["active_holds_total"]
    assert avail == 9850.0
    assert holds == 150.0

    # 3. Settle segment upon preemption
    seg_payload = {
        "reservation_id": res_id,
        "segment_credits": 30.0,
    }
    resp_seg = client.post(
        "/v1/budget/settle-segment",
        json=seg_payload,
        headers={"X-Hexaqueue-User": "alice"},
    )
    seg_code = resp_seg.status_code
    assert seg_code == 200
    seg_data = resp_seg.json()
    seg_status = seg_data["status"]
    cum = seg_data["cumulative_credits"]
    assert seg_status == "SEGMENT_SETTLED"
    assert cum == 30.0


def test_budget_release_api(
    hermetic_api_client: TestClient,
) -> None:
    """Verify POST /v1/budget/release releases held credits back to tenant."""
    client = hermetic_api_client

    # 1. Place a reservation
    reserve_payload = {
        "tenant_id": "tenant-cancel",
        "job_id": "job-cancel-1",
        "estimated_credits": 250.0,
    }
    resp_reserve = client.post(
        "/v1/budget/reserve",
        json=reserve_payload,
        headers={"X-Hexaqueue-User": "alice"},
    )
    res_code = resp_reserve.status_code
    assert res_code == 200
    res_id = resp_reserve.json()["reservation_id"]

    # 2. Release reservation
    rel_payload = {
        "reservation_id": res_id,
    }
    resp_rel = client.post(
        "/v1/budget/release",
        json=rel_payload,
        headers={"X-Hexaqueue-User": "alice"},
    )
    rel_code = resp_rel.status_code
    assert rel_code == 200
    rel_data = resp_rel.json()
    rel_status = rel_data["status"]
    assert rel_status == "RELEASED"

    # 3. Verify balance restored
    resp_bal = client.get(
        "/v1/budget/tenants/tenant-cancel",
        headers={"X-Hexaqueue-User": "alice"},
    )
    bal_code = resp_bal.status_code
    assert bal_code == 200
    bal_data = resp_bal.json()
    avail = bal_data["available_balance"]
    holds = bal_data["active_holds_total"]
    assert avail == 10000.0
    assert holds == 0.0


def test_cluster_health_api(
    hermetic_api_client: TestClient,
) -> None:
    """Verify GET /v1/cluster/health returns aggregated health metrics."""
    client = hermetic_api_client

    resp_health = client.get(
        "/v1/cluster/health",
        headers={"X-Hexaqueue-User": "operator"},
    )
    health_code = resp_health.status_code
    assert health_code == 200
    health_data = resp_health.json()
    assert "healthy_nodes_count" in health_data
    assert "total_cpus" in health_data
    assert "active_jobs_count" in health_data


def test_budget_report_columnar_api(
    hermetic_api_client: TestClient,
) -> None:
    """Verify GET /v1/budget/report with JSON and binary columnar projections."""
    client = hermetic_api_client

    # 1. JSON report
    resp_json = client.get(
        "/v1/budget/report?window_hours=12&format=json",
        headers={"X-Hexaqueue-User": "operator"},
    )
    res_code = resp_json.status_code
    assert res_code == 200
    report_data = resp_json.json()
    assert "total_spend_credits" in report_data
    assert "burn_rate_credits_per_hour" in report_data
    assert report_data["window_hours"] == 12

    # 2. Binary Parquet stream
    resp_parquet = client.get(
        "/v1/budget/report?format=parquet",
        headers={"X-Hexaqueue-User": "operator"},
    )
    parquet_code = resp_parquet.status_code
    assert parquet_code == 200
    res_ct = resp_parquet.headers.get("content-type")
    assert "parquet" in (res_ct or "")

    # 3. Arrow IPC stream
    resp_arrow = client.get(
        "/v1/budget/report?format=arrow_ipc",
        headers={"X-Hexaqueue-User": "operator"},
    )
    arrow_code = resp_arrow.status_code
    assert arrow_code == 200
    res_arrow_ct = resp_arrow.headers.get("content-type")
    assert "arrow" in (res_arrow_ct or "")
