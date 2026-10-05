"""Unit tests for worker container domain configurations (Issue #30)."""

from hexaqueue_worker.domain.container import ApptainerConfig, PodmanConfig


def test_podman_config_defaults_and_overrides() -> None:
    """Verify PodmanConfig default settings and custom overrides."""
    config = PodmanConfig()
    exe = config.executable_path
    assert exe == "podman"
    rootless = config.rootless
    assert rootless is True
    userns = config.userns_mode
    assert userns == "keep-id"
    net = config.network_mode
    assert net == "none"
    relabel = config.selinux_relabel
    assert relabel is True

    custom = PodmanConfig(
        executable_path="/usr/bin/podman",
        default_image="python:3.13-alpine",
        network_mode="bridge",
        read_only_rootfs=True,
    )
    custom_exe = custom.executable_path
    assert custom_exe == "/usr/bin/podman"
    custom_img = custom.default_image
    assert custom_img == "python:3.13-alpine"
    custom_net = custom.network_mode
    assert custom_net == "bridge"
    custom_ro = custom.read_only_rootfs
    assert custom_ro is True


def test_apptainer_config_defaults_and_overrides() -> None:
    """Verify ApptainerConfig default settings and custom overrides."""
    config = ApptainerConfig()
    exe = config.executable_path
    assert exe == "apptainer"
    contain = config.containall
    assert contain is True
    clean = config.cleanenv
    assert clean is True
    nv = config.nv_gpu
    assert nv is True
    rocm = config.rocm_gpu
    assert rocm is False
    tmpfs = config.writable_tmpfs
    assert tmpfs is True

    custom = ApptainerConfig(
        executable_path="/usr/bin/singularity",
        nv_gpu=False,
        rocm_gpu=True,
    )
    custom_exe = custom.executable_path
    assert custom_exe == "/usr/bin/singularity"
    custom_nv = custom.nv_gpu
    assert custom_nv is False
    custom_rocm = custom.rocm_gpu
    assert custom_rocm is True
