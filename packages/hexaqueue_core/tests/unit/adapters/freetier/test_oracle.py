"""Unit tests for NaiveFreeTierMeshOracle reference model."""

from hexaqueue_core.adapters.freetier.oracle import NaiveFreeTierMeshOracle


def test_oracle_allocation_and_release() -> None:
    """Test sequential allocation and release on oracle."""
    oracle = NaiveFreeTierMeshOracle()

    # Allocate job 1
    res1 = oracle.step_allocate("j1", cpus=2, ram_mb=1024, preferred="GCP")
    assert res1 == "GCP"
    active = oracle.active_job_count
    assert active == 1
    cpus = oracle.total_allocated_cpus
    assert cpus == 2

    # Allocate job 2 on OCI (high RAM)
    res2 = oracle.step_allocate("j2", cpus=4, ram_mb=8192, preferred="OCI")
    assert res2 == "OCI"
    active2 = oracle.active_job_count
    assert active2 == 2

    # Exceed GCP quota
    res_exceed = oracle.step_allocate("j3", cpus=2, ram_mb=1024, preferred="GCP")
    # GCP full, falls back to another eligible provider with 2 cpus and 1024 mb (e.g. LOCAL)
    assert res_exceed in ("LOCAL", "OCI")

    # Duplicate job id rejected
    dup = oracle.step_allocate("j1", cpus=1, ram_mb=512)
    assert dup is None

    # Release
    rel = oracle.step_release("j1")
    assert rel is True
    rel_missing = oracle.step_release("nonexistent")
    assert rel_missing is False
