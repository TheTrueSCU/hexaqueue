"""Virtual machine and microVM worker configuration models.

Notes/Architectural Intent:
    Encapsulates host-level hypervisor binaries, virtualization flags,
    and socket endpoints for running isolated VM workloads on compute workers.
"""

from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_core.domain.vm import HypervisorBackend


class MicroVmConfig(BaseModel):
    """Configuration for hypervisor execution runtimes on a worker node.

    Args:
        cloud_hypervisor_binary: Path or command name for cloud-hypervisor executable.
        default_backend: Fallback hypervisor backend if not specified on the job.
        default_timeout_seconds: Maximum default runtime in seconds before kill.
        enable_kvm: Whether to attempt KVM acceleration on the host.
        firecracker_binary: Path or command name for Firecracker executable.
        qemu_binary: Path or command name for QEMU executable.
        socket_dir: Ephemeral directory on host for hypervisor control sockets and logs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cloud_hypervisor_binary: str = Field(
        default="cloud-hypervisor",
        description="Executable command or path for cloud-hypervisor",
    )
    default_backend: HypervisorBackend = Field(
        default=HypervisorBackend.QEMU,
        description="Default hypervisor if omitted on job specification",
    )
    default_timeout_seconds: int = Field(
        default=3600, ge=1, description="Default job timeout limit in seconds"
    )
    enable_kvm: bool = Field(
        default=True, description="Enable hardware-accelerated KVM virtualization"
    )
    firecracker_binary: str = Field(
        default="firecracker",
        description="Executable command or path for Firecracker",
    )
    qemu_binary: str = Field(
        default="qemu-system-x86_64",
        description="Executable command or path for QEMU",
    )
    socket_dir: str = Field(
        default="/tmp/hexaqueue-vms",
        description="Host directory for VM sockets and consoles",
    )
