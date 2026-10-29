"""Virtual Machine (VM) and MicroVM execution domain models.

Notes/Architectural Intent:
    Defines hardware-level virtualization specifications for workloads requiring
    dedicated kernels, Windows hypervisor isolation, PCIe/GPU device passthrough,
    or Firecracker/QEMU microsecond-boot containment.
"""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HypervisorBackend(StrEnum):
    """Supported hardware virtualization and hypervisor engines.

    Engines:
        QEMU: Universal hypervisor supporting full OS virtualization and Windows virtio.
        FIRECRACKER: Minimalist AWS microVM hypervisor with sub-100ms boot times.
        CLOUD_HYPERVISOR: Rust-based modern hypervisor focused on cloud workloads.
    """

    CLOUD_HYPERVISOR = "cloud-hypervisor"
    FIRECRACKER = "firecracker"
    QEMU = "qemu"


class VmSpec(BaseModel):
    """Specification of a Virtual Machine execution runtime environment.

    Args:
        image: Path to base disk image, OS_IMAGE collateral hash, or cloud image URI.
        backend: Target hypervisor engine.
        vcpus: Number of virtual CPU cores allocated to the guest.
        ram_mb: Amount of RAM allocated in megabytes.
        kernel_path: Optional path to uncompressed guest kernel image (vmlinux).
        kernel_args: Boot parameters passed to guest kernel.
        enable_kvm: Whether to enable hardware-assisted virtualization (KVM).
        passthrough_devices: List of host PCIe/GPU addresses or devices for guest passthrough.
        guest_agent: Whether to enable QEMU guest agent for command execution.
        workdir: Guest working directory for job execution.
        is_windows: Whether the guest OS is Windows.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: HypervisorBackend = Field(
        default=HypervisorBackend.QEMU, description="Hypervisor virtualization engine"
    )
    enable_kvm: bool = Field(
        default=True, description="Enable hardware-accelerated KVM virtualization"
    )
    guest_agent: bool = Field(
        default=True, description="Enable guest agent communications"
    )
    image: str = Field(description="Disk image path, collateral hash, or image URI")
    is_windows: bool = Field(
        default=False, description="Flag indicating guest is Microsoft Windows"
    )
    kernel_args: str = Field(
        default="console=ttyS0 reboot=k panic=1",
        description="Guest kernel command-line boot arguments",
    )
    kernel_path: str | None = Field(
        default=None, description="Path to kernel image (e.g. for Firecracker)"
    )
    passthrough_devices: list[str] = Field(
        default_factory=list, description="Host devices for guest passthrough"
    )
    ram_mb: int = Field(default=1024, ge=128, description="Guest memory in megabytes")
    vcpus: int = Field(default=1, ge=1, description="Guest virtual CPU core count")
    workdir: str = Field(default="/workspace", description="Guest workdir path")

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate non-empty image reference.

        Returns:
            Validated instance.

        Raises:
            ValueError: If image is empty or whitespace.
        """
        if not self.image.strip():
            msg = "image cannot be empty"
            raise ValueError(msg)
        return self
