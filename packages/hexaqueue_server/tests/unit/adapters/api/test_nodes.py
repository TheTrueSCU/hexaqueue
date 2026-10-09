"""Tests for compute worker node telemetry, registration, and heartbeat endpoints."""

from fastapi.testclient import TestClient


def test_nodes_telemetry_and_ssh(hermetic_api_client: TestClient) -> None:
    """Verify node telemetry pulses query and bastion SSH session creation."""
    client = hermetic_api_client

    # 1. Get telemetry pulses
    resp_nodes = client.get("/v1/nodes", headers={"X-Hexaqueue-User": "operator"})
    nodes_code = resp_nodes.status_code
    assert nodes_code == 200
    pulses = resp_nodes.json()
    pulse_count = len(pulses)
    assert pulse_count >= 1

    # 2. Launch bastion SSH
    resp_ssh = client.post(
        "/v1/nodes/node-local-01/ssh?elevate=true",
        headers={"X-Hexaqueue-User": "operator"},
    )
    ssh_code = resp_ssh.status_code
    assert ssh_code == 200
    ssh_data = resp_ssh.json()
    assert "session_id" in ssh_data


def test_nodes_registration_heartbeat_and_profiles(
    hermetic_api_client: TestClient,
) -> None:
    """Verify compute node profile registration, heartbeat pulse, and profile listing."""
    client = hermetic_api_client

    # 1. Register node
    resp_reg = client.post(
        "/v1/nodes/register",
        json={
            "profile": {
                "node_id": "api-worker-test",
                "tier": "STATIC",
                "health_state": "HEALTHY",
            }
        },
        headers={"X-Hexaqueue-User": "worker-daemon"},
    )
    reg_code = resp_reg.status_code
    assert reg_code == 201
    assert resp_reg.json()["status"] == "REGISTERED"

    # 2. Heartbeat node
    resp_hb = client.post(
        "/v1/nodes/heartbeat",
        json={
            "worker_id": "api-worker-test",
            "active_job_ids": ["job-api-1"],
            "cached_collateral_hashes": ["sha256-test-hash"],
        },
        headers={"X-Hexaqueue-User": "worker-daemon"},
    )
    hb_code = resp_hb.status_code
    assert hb_code == 200
    hb_data = resp_hb.json()
    assert hb_data["node_id"] == "api-worker-test"
    assert "sha256-test-hash" in hb_data["cached_collateral_hashes"]

    # 3. List profiles
    resp_profiles = client.get(
        "/v1/nodes/profiles", headers={"X-Hexaqueue-User": "operator"}
    )
    prof_code = resp_profiles.status_code
    assert prof_code == 200
    prof_data = resp_profiles.json()
    total_nodes = prof_data["total_nodes"]
    assert total_nodes >= 1
