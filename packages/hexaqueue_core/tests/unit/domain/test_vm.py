"""Unit tests for virtual machine execution domain models."""

import pytest
from pydantic import ValidationError

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.vm import HypervisorBackend, VmSpec


def test_vmspec_valid_qemu() -> None:
    """Verify valid VmSpec with QEMU backend."""
    vm = VmSpec(
        image="/var/lib/images/ubuntu-noble.qcow2",
        backend=HypervisorBackend.QEMU,
        vcpus=4,
        ram_mb=4096,
        enable_kvm=True,
        passthrough_devices=["0000:01:00.0"],
        is_windows=False,
    )
    img = vm.image
    assert img == "/var/lib/images/ubuntu-noble.qcow2"
    backend = vm.backend
    assert backend == HypervisorBackend.QEMU
    cpus = vm.vcpus
    assert cpus == 4
    mem = vm.ram_mb
    assert mem == 4096
    kvm = vm.enable_kvm
    assert kvm is True
    pt = vm.passthrough_devices
    assert len(pt) == 1


def test_vmspec_valid_firecracker() -> None:
    """Verify valid VmSpec with Firecracker microVM backend."""
    vm = VmSpec(
        image="/var/lib/images/rootfs.ext4",
        backend=HypervisorBackend.FIRECRACKER,
        kernel_path="/var/lib/images/vmlinux",
        kernel_args="console=ttyS0 reboot=k panic=1",
        vcpus=2,
        ram_mb=512,
    )
    backend = vm.backend
    assert backend == HypervisorBackend.FIRECRACKER
    kpath = vm.kernel_path
    assert kpath == "/var/lib/images/vmlinux"


def test_vmspec_empty_image_error() -> None:
    """Verify empty image string raises ValidationError."""
    with pytest.raises(ValidationError, match="image cannot be empty"):
        VmSpec(image="")


def test_jobspec_with_vm_specification() -> None:
    """Verify JobSpec integration with optional vm field."""
    vm = VmSpec(image="ami-windows-2022", is_windows=True)
    job = JobSpec(
        id="job-vm-101",
        run_id="run-1",
        name="windows-driver-test",
        command="powershell.exe -File test.ps1",
        vm=vm,
    )
    job_vm = job.vm
    assert job_vm is not None
    is_win = job_vm.is_windows
    assert is_win is True
