"""Unit tests for Linux Cgroups v2 domain models and limit generation."""

import pytest
from pydantic import ValidationError

from hexaqueue_worker.domain.cgroups import CgroupConfig, CgroupLimits


def test_cgroup_limits_from_resources() -> None:
    """Verify standard cgroup limit derivation from CPU and RAM requirements."""
    limits = CgroupLimits.from_resources(cpus=4, ram_mb=2048)

    period = limits.cpu_period_us
    quota = limits.cpu_quota_us
    mem_max = limits.memory_max_bytes
    mem_high = limits.memory_high_bytes

    assert period == 100_000
    assert quota == 400_000
    assert mem_max == 2048 * 1024 * 1024
    assert mem_high == int(mem_max * 0.9)

    cpu_str = limits.cpu_max_str
    mem_str = limits.memory_max_str
    high_str = limits.memory_high_str

    assert cpu_str == "400000 100000"
    assert mem_str == str(2048 * 1024 * 1024)
    assert high_str == str(int(2048 * 1024 * 1024 * 0.9))


def test_cgroup_limits_unlimited() -> None:
    """Verify string formatting for unlimited CPU and memory bounds."""
    limits = CgroupLimits(
        cpu_quota_us=-1,
        memory_max_bytes=-1,
        memory_high_bytes=None,
    )
    cpu_str = limits.cpu_max_str
    mem_str = limits.memory_max_str
    high_str = limits.memory_high_str

    assert cpu_str == "max 100000"
    assert mem_str == "max"
    assert high_str is None

    limits_high_unlimited = CgroupLimits(
        cpu_quota_us=-1,
        memory_max_bytes=-1,
        memory_high_bytes=-1,
    )
    high_unlimited_str = limits_high_unlimited.memory_high_str
    assert high_unlimited_str == "max"


def test_cgroup_limits_validation_error() -> None:
    """Verify validation when memory_high_bytes exceeds memory_max_bytes."""
    with pytest.raises(ValidationError):
        CgroupLimits(
            cpu_quota_us=100000,
            memory_max_bytes=1000,
            memory_high_bytes=2000,
        )


def test_cgroup_config_defaults_and_validation() -> None:
    """Verify CgroupConfig defaults and non-empty string validation."""
    config = CgroupConfig()
    root = config.cgroup_fs_root
    prefix = config.cgroup_name_prefix

    assert root == "/sys/fs/cgroup/hexaqueue"
    assert prefix == "hq-"

    with pytest.raises(ValidationError):
        CgroupConfig(cgroup_fs_root="")

    with pytest.raises(ValidationError):
        CgroupConfig(cgroup_name_prefix="")
