"""Linux Cgroups v2 configuration and limit domain models.

Notes/Architectural Intent:
    Defines the mathematical translation between high-level JobSpec resource bounds
    (CPU cores, memory in MB) and low-level Linux Cgroups v2 control interface parameters
    (cpu.max quota/period, memory.max bytes, and memory.high throttling thresholds).
"""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CgroupLimits(BaseModel):
    """Calculated cgroup v2 control interface parameter values.

    Args:
        cpu_period_us: CFS enforcement period in microseconds (typically 100,000 us = 100ms).
        cpu_quota_us: CPU execution time allowed per period in microseconds, or -1 for max.
        memory_max_bytes: Hard memory ceiling in bytes, or -1 for max.
        memory_high_bytes: Optional memory throttle watermark in bytes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cpu_period_us: int = Field(
        default=100_000,
        gt=0,
        description="CPU enforcement period in microseconds",
    )
    cpu_quota_us: int = Field(
        description="Allowed CPU time per period in microseconds (-1 for unlimited)"
    )
    memory_high_bytes: int | None = Field(
        default=None,
        description="Memory throttling threshold in bytes",
    )
    memory_max_bytes: int = Field(
        description="Hard memory limit in bytes (-1 for unlimited)"
    )

    @classmethod
    def from_resources(cls, cpus: int, ram_mb: int) -> Self:
        """Derive standard cgroup v2 parameter limits from job resource requirements.

        Args:
            cpus: Number of requested CPU cores (minimum 1).
            ram_mb: Number of requested RAM megabytes (minimum 1).

        Returns:
            Calculated CgroupLimits instance.
        """
        period = 100_000
        quota = cpus * period
        mem_max = ram_mb * 1024 * 1024
        mem_high = int(mem_max * 0.9)
        return cls(
            cpu_period_us=period,
            cpu_quota_us=quota,
            memory_max_bytes=mem_max,
            memory_high_bytes=mem_high,
        )

    @property
    def cpu_max_str(self) -> str:
        """Format value string for writing into the cpu.max cgroup control file.

        Returns:
            String formatted as '<quota> <period>' or 'max <period>'.
        """
        if self.cpu_quota_us < 0:
            return f"max {self.cpu_period_us}"
        return f"{self.cpu_quota_us} {self.cpu_period_us}"

    @property
    def memory_max_str(self) -> str:
        """Format value string for writing into the memory.max cgroup control file.

        Returns:
            String formatted as integer byte count or 'max'.
        """
        if self.memory_max_bytes < 0:
            return "max"
        return str(self.memory_max_bytes)

    @property
    def memory_high_str(self) -> str | None:
        """Format value string for writing into the memory.high control file.

        Returns:
            String formatted as integer byte count or None if unspecified.
        """
        if self.memory_high_bytes is None:
            return None
        if self.memory_high_bytes < 0:
            return "max"
        return str(self.memory_high_bytes)

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate cgroup limit consistency."""
        if (
            self.memory_high_bytes is not None
            and self.memory_high_bytes > 0
            and self.memory_max_bytes > 0
            and self.memory_high_bytes > self.memory_max_bytes
        ):
            msg = (
                f"memory_high_bytes ({self.memory_high_bytes}) cannot exceed "
                f"memory_max_bytes ({self.memory_max_bytes})"
            )
            raise ValueError(msg)
        return self


class CgroupConfig(BaseModel):
    """Configuration options for Linux cgroups v2 hierarchy management.

    Args:
        cgroup_fs_root: Absolute filesystem root path for Hexaqueue cgroups.
        cgroup_name_prefix: Prefix used for per-job cgroup directories.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cgroup_fs_root: str = Field(
        default="/sys/fs/cgroup/hexaqueue",
        description="Filesystem root directory for cgroups v2",
    )
    cgroup_name_prefix: str = Field(
        default="hq-", description="Directory prefix for individual job cgroups"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate non-empty paths and prefixes."""
        if not self.cgroup_fs_root.strip():
            msg = "cgroup_fs_root cannot be empty"
            raise ValueError(msg)
        if not self.cgroup_name_prefix.strip():
            msg = "cgroup_name_prefix cannot be empty"
            raise ValueError(msg)
        return self


__all__ = [
    "CgroupConfig",
    "CgroupLimits",
]
