"""Property-based fuzz tests for cgroups v2 resource limit calculations."""

from hypothesis import given
from hypothesis import strategies as st

from hexaqueue_worker.domain.cgroups import CgroupLimits


@given(
    cpus=st.integers(min_value=1, max_value=1024),
    ram_mb=st.integers(min_value=1, max_value=10_000_000),
)
def test_fuzz_cgroup_limits_derivation(cpus: int, ram_mb: int) -> None:
    """Property test verifying mathematical consistency of derived cgroup v2 limits."""
    limits = CgroupLimits.from_resources(cpus=cpus, ram_mb=ram_mb)

    expected_quota = cpus * 100_000
    expected_mem_max = ram_mb * 1024 * 1024
    expected_mem_high = int(expected_mem_max * 0.9)

    quota = limits.cpu_quota_us
    mem_max = limits.memory_max_bytes
    mem_high = limits.memory_high_bytes

    assert quota == expected_quota
    assert mem_max == expected_mem_max
    assert mem_high == expected_mem_high

    assert mem_high <= mem_max

    cpu_str = limits.cpu_max_str
    mem_str = limits.memory_max_str
    high_str = limits.memory_high_str

    assert cpu_str == f"{expected_quota} 100000"
    assert mem_str == str(expected_mem_max)
    assert high_str == str(expected_mem_high)
