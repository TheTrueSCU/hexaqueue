"""GitHub runner label parser and resource translator.

Notes/Architectural Intent:
    Translates GitHub Actions 'runs-on' labels into concrete Hexaqueue
    ResourceRequirements. Extracts requested CPU count, RAM capacity, GPU models,
    scratch disk quotas, and walltime ceilings using deterministic regex parsing.
"""

import re

from hexaqueue_core.domain.resources import ResourceRequirements

_CPU_REGEX = re.compile(r"^(?:cpu-)?(\d+)(?:-cores?|-cpus?)?$", re.IGNORECASE)
_RAM_REGEX = re.compile(r"^(?:ram-)?(\d+)(?:-)?(?:gb|gib)(?:-ram)?$", re.IGNORECASE)
_SCRATCH_REGEX = re.compile(
    r"^(?:scratch-)?(\d+)(?:-)?(?:gb|gib)(?:-scratch)?$", re.IGNORECASE
)
_WALLTIME_MINUTES_REGEX = re.compile(
    r"^(?:walltime-)?(\d+)(?:-)?(?:m|min|minutes?)(?:-walltime)?$", re.IGNORECASE
)
_WALLTIME_HOURS_REGEX = re.compile(
    r"^(?:walltime-)?(\d+)(?:-)?(?:h|hr|hours?)(?:-walltime)?$", re.IGNORECASE
)

_KNOWN_GPUS = {
    "h100": "h100",
    "a100": "a100",
    "a10g": "a10g",
    "l4": "l4",
    "l40": "l40",
    "t4": "t4",
    "v100": "v100",
    "rtx4090": "rtx4090",
    "rtx3090": "rtx3090",
}


class LabelTranslator:
    """Translates GitHub Actions runner labels into Hexaqueue ResourceRequirements.

    Args:
        default_cpus: Baseline CPU count if not specified (default 2).
        default_ram_mb: Baseline RAM in MB if not specified (default 4096).
        default_scratch_mb: Baseline scratch disk in MB (default 10240).
        default_walltime_seconds: Default walltime ceiling (default 7200).

    Notes/Architectural Intent:
        Prevents job starvation or over-allocation by converting informal
        CI label annotations into bounded hardware resource claims.
    """

    def __init__(
        self,
        default_cpus: int = 2,
        default_ram_mb: int = 4096,
        default_scratch_mb: int = 10240,
        default_walltime_seconds: int = 7200,
    ) -> None:
        self.default_cpus = default_cpus
        self.default_ram_mb = default_ram_mb
        self.default_scratch_mb = default_scratch_mb
        self.default_walltime_seconds = default_walltime_seconds

    def translate(self, labels: list[str]) -> ResourceRequirements:
        """Parse runner labels and synthesize concrete ResourceRequirements.

        Args:
            labels: List of label strings from GitHub workflow job 'runs-on'.

        Returns:
            Configured ResourceRequirements instance.
        """
        cpus = self.default_cpus
        ram_mb = self.default_ram_mb
        scratch_mb = self.default_scratch_mb
        walltime = self.default_walltime_seconds
        gpus = 0
        gpu_model: str | None = None

        for raw_label in labels:
            clean = raw_label.strip().lower()
            if clean in ("self-hosted", "linux", "x64", "arm64", "hexaqueue"):
                continue

            gpu_res = self._parse_gpu(clean)
            if gpu_res:
                gpus = max(gpus, gpu_res[0])
                gpu_model = gpu_res[1] or gpu_model
                continue

            parsed_cpu = self._parse_cpu(clean)
            if parsed_cpu is not None:
                cpus = parsed_cpu
                continue

            parsed_ram = self._parse_ram(clean)
            if parsed_ram is not None:
                ram_mb = parsed_ram
                continue

            parsed_scratch = self._parse_scratch(clean)
            if parsed_scratch is not None:
                scratch_mb = parsed_scratch
                continue

            parsed_wt = self._parse_walltime(clean)
            if parsed_wt is not None:
                walltime = parsed_wt

        return ResourceRequirements(
            cpus=cpus,
            ram_mb=ram_mb,
            gpus=gpus,
            gpu_model=gpu_model,
            scratch_mb=scratch_mb,
            walltime_seconds=walltime,
        )

    def _parse_gpu(self, label: str) -> tuple[int, str | None] | None:
        """Check if label matches a GPU model or quantity."""
        clean = label.replace("gpu-", "")
        for key, model in _KNOWN_GPUS.items():
            if clean == key or label == f"gpu-{key}":
                return (1, model)

        match = re.match(r"^(\d+)x?-gpu(?:-(\w+))?$", label)
        if match:
            qty = int(match.group(1))
            model_name = _KNOWN_GPUS.get(match.group(2)) if match.group(2) else None
            return (qty, model_name)
        return None

    def _parse_cpu(self, label: str) -> int | None:
        """Parse CPU count from label."""
        if ("core" not in label and "cpu" not in label) or (
            "ram" in label or "scratch" in label
        ):
            return None
        match = _CPU_REGEX.match(label)
        return max(1, int(match.group(1))) if match else None

    def _parse_ram(self, label: str) -> int | None:
        """Parse RAM MB from label."""
        if "scratch" in label or "core" in label:
            return None
        match = _RAM_REGEX.match(label)
        return max(128, int(match.group(1)) * 1024) if match else None

    def _parse_scratch(self, label: str) -> int | None:
        """Parse scratch disk MB from label."""
        if "scratch" not in label:
            return None
        match = _SCRATCH_REGEX.match(label)
        return int(match.group(1)) * 1024 if match else None

    def _parse_walltime(self, label: str) -> int | None:
        """Parse walltime seconds from label."""
        if "m" in label or "min" in label:
            wt_min = _WALLTIME_MINUTES_REGEX.match(label)
            if wt_min:
                return max(10, int(wt_min.group(1)) * 60)
        if "h" in label or "hr" in label:
            wt_hr = _WALLTIME_HOURS_REGEX.match(label)
            if wt_hr:
                return max(10, int(wt_hr.group(1)) * 3600)
        return None


__all__ = [
    "LabelTranslator",
]
