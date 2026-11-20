"""Tests for budget accounting, reservation holds, strategy switching, and cluster health REST endpoints."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from hexaqueue_core.adapters.storage.presigned import InMemoryPresignedStorageAdapter
from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.lease import TestSliceDispatch
from hexaqueue_core.domain.pool import InstancePoolState
from hexaqueue_server.adapters.api.app import create_server_app
from hexaqueue_server.adapters.cloud.oci import OciInstancePoolAdapter
from hexaqueue_server.domain.autoscaler import (
    BudgetAwareInstancePoolAutoscaler,
    BudgetStrategyMode,
    CreditPacingPolicy,
)
from hexaqueue_server.domain.lease_coordinator import SliceLeaseCoordinator


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


def test_budget_strategy_get_and_runtime_put_api(
    hermetic_api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify GET and elevated PUT /v1/budget/strategy runtime strategy switching."""
    for var in (
        "HEXAQUEUE_BUDGET_STRATEGY",
        "HEXAQUEUE_CREDIT_EXPIRY_DATE",
        "HEXAQUEUE_DAILY_CAP_USD",
    ):
        monkeypatch.delenv(var, raising=False)

    client = hermetic_api_client

    # 1. Default state before explicit policy is configured
    resp_init = client.get(
        "/v1/budget/strategy",
        headers={"X-Hexaqueue-User": "operator"},
    )
    init_code = resp_init.status_code
    assert init_code == 200
    init_data = resp_init.json()
    init_configured = init_data["configured"]
    init_strategy = init_data["strategy"]
    init_available = init_data["available_strategies"]
    assert init_configured is False
    assert init_strategy == "UNCONSTRAINED"
    assert "LINEAR_CREDIT_PACING" in init_available
    assert "FREE_TIER_ONLY" in init_available

    # 2. Non-elevated PUT is rejected with 403 Forbidden
    resp_denied = client.put(
        "/v1/budget/strategy",
        json={"strategy": "FREE_TIER_ONLY"},
        headers={"X-Hexaqueue-User": "alice"},
    )
    denied_code = resp_denied.status_code
    assert denied_code == 403

    # 3. Elevated PUT sets LINEAR_CREDIT_PACING with credit balances & expiry
    future_expiry = (datetime.now(UTC) + timedelta(days=10)).replace(microsecond=0)
    resp_linear = client.put(
        "/v1/budget/strategy",
        json={
            "strategy": "LINEAR_CREDIT_PACING",
            "total_credits_usd": 300.0,
            "spent_credits_usd": 1.53,
            "reserve_credits_usd": 15.0,
            "hourly_cost_per_node_usd": 0.046,
            "expiry_time": future_expiry.isoformat(),
        },
        headers={"X-Hexaqueue-User": "operator", "X-Hexaqueue-Elevate": "true"},
    )
    linear_code = resp_linear.status_code
    assert linear_code == 200
    linear_data = resp_linear.json()
    linear_configured = linear_data["configured"]
    linear_strategy = linear_data["strategy"]
    linear_rem = linear_data["spendable_remaining_usd"]
    linear_nodes = linear_data["recommended_max_nodes"]
    assert linear_configured is True
    assert linear_strategy == "LINEAR_CREDIT_PACING"
    assert linear_rem == pytest.approx(283.47, abs=0.01)
    assert linear_nodes == 10

    # 4. Toggle to FREE_TIER_ONLY -> prior credit balances & expiry preserved, 0 nodes
    resp_free = client.put(
        "/v1/budget/strategy",
        json={"strategy": "FREE_TIER_ONLY"},
        headers={"X-Hexaqueue-User": "operator", "X-Hexaqueue-Elevate": "true"},
    )
    free_code = resp_free.status_code
    assert free_code == 200
    free_data = resp_free.json()
    free_strategy = free_data["strategy"]
    free_total = free_data["total_credits_usd"]
    free_spent = free_data["spent_credits_usd"]
    free_expiry = free_data["expiry_time"]
    free_allowance = free_data["daily_allowance_usd"]
    free_nodes = free_data["recommended_max_nodes"]
    assert free_strategy == "FREE_TIER_ONLY"
    assert free_total == 300.0
    assert free_spent == 1.53
    assert free_expiry is not None
    assert free_allowance == 0.0
    assert free_nodes == 0

    # 5. Switch to FIXED_DAILY_CAP and clear expiry -> expiry cleared, daily cap applied
    resp_fixed = client.put(
        "/v1/budget/strategy",
        json={
            "strategy": "FIXED_DAILY_CAP",
            "daily_cap_usd": 25.0,
            "clear_expiry": True,
        },
        headers={"X-Hexaqueue-User": "operator", "X-Hexaqueue-Elevate": "true"},
    )
    fixed_code = resp_fixed.status_code
    assert fixed_code == 200
    fixed_data = resp_fixed.json()
    assert fixed_data["strategy"] == "FIXED_DAILY_CAP"
    assert fixed_data["expiry_time"] is None
    assert fixed_data["daily_cap_usd"] == 25.0
    assert fixed_data["daily_allowance_usd"] == 25.0

    # 6. Switch to UNCONSTRAINED and confirm GET reflects final state
    resp_uncon = client.put(
        "/v1/budget/strategy",
        json={"strategy": "UNCONSTRAINED"},
        headers={"X-Hexaqueue-User": "operator", "X-Hexaqueue-Elevate": "true"},
    )
    uncon_code = resp_uncon.status_code
    assert uncon_code == 200
    uncon_data = resp_uncon.json()
    assert uncon_data["strategy"] == "UNCONSTRAINED"
    assert uncon_data["daily_allowance_usd"] is None

    resp_get = client.get(
        "/v1/budget/strategy",
        headers={"X-Hexaqueue-User": "operator"},
    )
    get_code = resp_get.status_code
    assert get_code == 200
    get_data = resp_get.json()
    assert get_data["strategy"] == "UNCONSTRAINED"
    assert get_data["total_credits_usd"] == 300.0


def test_budget_strategy_put_triggers_immediate_pool_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify PUT /v1/budget/strategy immediately reconciles live burst pool capacity."""
    monkeypatch.setenv("HEXAQUEUE_ALLOW_ANONYMOUS_ADMIN", "1")
    for var in (
        "HEXAQUEUE_BUDGET_STRATEGY",
        "HEXAQUEUE_CREDIT_EXPIRY_DATE",
        "HEXAQUEUE_DAILY_CAP_USD",
    ):
        monkeypatch.delenv(var, raising=False)

    app = create_server_app()
    coord = app.state.container.resolve(SliceLeaseCoordinator)
    coord._storage_port = InMemoryPresignedStorageAdapter()
    gov = OciInstancePoolAdapter()
    gov.register_mock_pool(
        InstancePoolState(
            pool_id="pool-a4",
            provider=CspProvider.OCI,
            min_nodes=0,
            max_nodes=6,
            current_nodes=2,
            desired_nodes=2,
            ready_nodes=2,
        )
    )
    autoscaler = BudgetAwareInstancePoolAutoscaler(
        governors={"pool-a4": gov},
        credit_pacing=CreditPacingPolicy(
            strategy=BudgetStrategyMode.LINEAR_CREDIT_PACING,
            total_credits_usd=300.0,
            spent_credits_usd=1.53,
            reserve_credits_usd=15.0,
            expiry_time=datetime.now(UTC) + timedelta(days=10),
        ),
    )
    coord._autoscaler = autoscaler
    coord._pool_id = "pool-a4"

    asyncio.run(
        coord.enqueue_session_slices(
            session_id="sess-reconcile",
            slices=[
                TestSliceDispatch(
                    slice_id="sl-1",
                    slice_index=0,
                    total_slices=1,
                    test_nodeids=["tests/test_a.py::test_ok"],
                )
            ],
            coverage_sources=["packages/core/src"],
        )
    )

    with TestClient(app) as client:
        resp = client.put(
            "/v1/budget/strategy",
            json={"strategy": "FREE_TIER_ONLY"},
            headers={"X-Hexaqueue-User": "operator", "X-Hexaqueue-Elevate": "true"},
        )
        resp_code = resp.status_code
        assert resp_code == 200
        data = resp.json()
        reconciled = data["reconcile_triggered"]
        strategy_out = data["strategy"]
        max_nodes_out = data["recommended_max_nodes"]
        assert reconciled is True
        assert strategy_out == "FREE_TIER_ONLY"
        assert max_nodes_out == 0

    final_pool = asyncio.run(gov.get_pool_state("pool-a4"))
    final_nodes = final_pool.current_nodes
    assert final_nodes == 0
