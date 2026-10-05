"""Domain configurations for container execution runtimes.

Notes/Architectural Intent:
    Provides structured configuration schemas for rootless Podman and
    HPC Apptainer/Singularity container runtime adapters.
"""

from pydantic import BaseModel, ConfigDict, Field


class PodmanConfig(BaseModel):
    """Configuration for rootless Podman container execution runtime.

    Args:
        executable_path: Path to the podman CLI binary.
        default_image: Fallback container image when JobSpec does not specify one.
        rootless: Whether to enforce rootless user namespace execution.
        userns_mode: User namespace mapping mode (e.g. 'keep-id').
        network_mode: Network isolation mode ('none', 'bridge', 'host').
        seccomp_profile: Path to custom seccomp profile or 'default'.
        read_only_rootfs: Enforce read-only root container filesystem.
        gpu_flag: CLI flag for GPU device attachment (e.g. '--gpus all').
        selinux_relabel: Append :Z to volume mounts for SELinux relabeling.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    executable_path: str = Field(default="podman", description="Podman binary path")
    default_image: str = Field(
        default="docker.io/library/alpine:latest", description="Default image"
    )
    rootless: bool = Field(default=True, description="Enforce rootless execution")
    userns_mode: str = Field(default="keep-id", description="User namespace mode")
    network_mode: str = Field(default="none", description="Container network isolation")
    seccomp_profile: str | None = Field(
        default=None, description="Seccomp profile path"
    )
    read_only_rootfs: bool = Field(
        default=False, description="Read-only root filesystem"
    )
    gpu_flag: str = Field(default="--gpus all", description="GPU attachment flag")
    selinux_relabel: bool = Field(
        default=True, description="Enable SELinux volume relabeling (:Z)"
    )


class ApptainerConfig(BaseModel):
    """Configuration for Apptainer / Singularity HPC container execution runtime.

    Args:
        executable_path: Path to the apptainer or singularity CLI binary.
        default_image: Fallback image or SIF path.
        containall: Enforce full container namespace and file containment.
        cleanenv: Clean all host environment variables before execution.
        nv_gpu: Enable NVIDIA GPU acceleration via '--nv'.
        rocm_gpu: Enable AMD ROCm GPU acceleration via '--rocm'.
        writable_tmpfs: Mount ephemeral writable tmpfs for temporary files.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    executable_path: str = Field(
        default="apptainer", description="Apptainer binary path"
    )
    default_image: str = Field(
        default="docker://alpine:latest", description="Default container image"
    )
    containall: bool = Field(default=True, description="Contain all namespaces")
    cleanenv: bool = Field(default=True, description="Clean host environment")
    nv_gpu: bool = Field(default=True, description="NVIDIA GPU support (--nv)")
    rocm_gpu: bool = Field(default=False, description="AMD ROCm GPU support (--rocm)")
    writable_tmpfs: bool = Field(
        default=True, description="Mount ephemeral writable tmpfs"
    )


__all__ = [
    "ApptainerConfig",
    "PodmanConfig",
]
