"""Unit tests for runner label translation."""

from hexaqueue_github_runner.domain.labels import LabelTranslator


def test_default_label_translation() -> None:
    """Test default values when no specific hardware labels are provided."""
    translator = LabelTranslator()
    res = translator.translate(["self-hosted", "linux", "x64"])
    assert res.cpus == 2
    assert res.ram_mb == 4096
    assert res.gpus == 0
    assert res.gpu_model is None
    assert res.scratch_mb == 10240
    assert res.walltime_seconds == 7200


def test_custom_hardware_label_translation() -> None:
    """Test translating explicit CPU, RAM, GPU, scratch, and walltime labels."""
    translator = LabelTranslator()
    labels = [
        "self-hosted",
        "linux",
        "16-cores",
        "64gb",
        "gpu-h100",
        "100gb-scratch",
        "2h-walltime",
    ]
    res = translator.translate(labels)
    assert res.cpus == 16
    assert res.ram_mb == 64 * 1024
    assert res.gpus == 1
    assert res.gpu_model == "h100"
    assert res.scratch_mb == 100 * 1024
    assert res.walltime_seconds == 7200


def test_multi_gpu_and_minutes_walltime() -> None:
    """Test parsing multi-GPU and minutes walltime labels."""
    translator = LabelTranslator()
    labels = ["self-hosted", "4-gpu-a100", "90m-walltime"]
    res = translator.translate(labels)
    assert res.gpus == 4
    assert res.gpu_model == "a100"
    assert res.walltime_seconds == 5400
