"""Unit tests for worker microVM domain configuration."""

from hexaqueue_core.domain.vm import HypervisorBackend
from hexaqueue_worker.domain.vm import MicroVmConfig


def test_micro_vm_config_defaults() -> None:
    """Verify default parameters for MicroVmConfig."""
    cfg = MicroVmConfig()
    qemu = cfg.qemu_binary
    assert qemu == "qemu-system-x86_64"
    fc = cfg.firecracker_binary
    assert fc == "firecracker"
    ch = cfg.cloud_hypervisor_binary
    assert ch == "cloud-hypervisor"
    backend = cfg.default_backend
    assert backend == HypervisorBackend.QEMU
    kvm = cfg.enable_kvm
    assert kvm is True


def test_micro_vm_config_custom() -> None:
    """Verify custom MicroVmConfig fields."""
    cfg = MicroVmConfig(
        qemu_binary="/usr/local/bin/qemu",
        default_backend=HypervisorBackend.FIRECRACKER,
        socket_dir="/var/run/fc-sockets",
        enable_kvm=False,
    )
    qemu = cfg.qemu_binary
    assert qemu == "/usr/local/bin/qemu"
    backend = cfg.default_backend
    assert backend == HypervisorBackend.FIRECRACKER
    kvm = cfg.enable_kvm
    assert kvm is False
