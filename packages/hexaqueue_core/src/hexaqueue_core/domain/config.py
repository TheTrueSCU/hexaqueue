"""Hexaqueue configuration domain models extending Hexastack configuration foundations.

Notes/Architectural Intent:
    Leverages Hexastack configuration models and section getters while defining
    Hexaqueue-specific cluster topology, execution modes (including Free-Tier guards),
    and provider profiles.
"""

from enum import StrEnum

from hexastack_core.domain.config import HexastackConfig, HexastackCoreConfig
from pydantic import BaseModel, Field

from hexaqueue_core.domain.exceptions import HexaqueueConfigError


class ExecutionMode(StrEnum):
    """Overarching operational mode for the Hexaqueue cluster.

    Modes:
        PRODUCTION: Standard production scheduling with active dynamic cloud scaling.
        DEVELOPMENT: Relaxed validation and verbose debug hooks for local iteration.
        FREE_TIER: Strict zero-cost governor clamping compute/storage to CSP free limits.
    """

    PRODUCTION = "PRODUCTION"
    DEVELOPMENT = "DEVELOPMENT"
    FREE_TIER = "FREE_TIER"


class CspProvider(StrEnum):
    """Target Cloud Service Provider or infrastructure environment."""

    AWS = "AWS"
    AZURE = "AZURE"
    GCP = "GCP"
    LOCAL = "LOCAL"
    OCI = "OCI"
    ONPREM = "ONPREM"


class FreeTierProfileConfig(BaseModel):
    """Clamping thresholds for zero-cost CSP Free-Tier execution.

    Args:
        max_cpus: Maximum total vCPUs permitted across the cluster.
        max_ram_mb: Maximum total RAM permitted across the cluster in MB.
        max_gpus: Maximum GPUs permitted (strictly 0 on free tiers).
        max_storage_mb: Maximum total persistent storage permitted in MB.
        allowed_regions: Explicit list of zero-cost regions (e.g. ['us-central1', 'us-east1']).
    """

    max_cpus: int = Field(default=2, ge=1)
    max_ram_mb: int = Field(default=1024, ge=128)
    max_gpus: int = Field(default=0, ge=0)
    max_storage_mb: int = Field(default=5120, ge=512)  # Default: 5 GB object storage
    allowed_regions: list[str] = Field(default_factory=list)


class HexaqueueCoreConfig(HexastackCoreConfig):
    """Core Hexaqueue configuration model extending HexastackCoreConfig.

    Args:
        cluster_id: Unique cluster identifier.
        mode: Active ExecutionMode (PRODUCTION, DEVELOPMENT, FREE_TIER).
        csp_provider: Target CSP or ONPREM environment.
        free_tier: FreeTierProfileConfig active when mode is FREE_TIER.
    """

    cluster_id: str = Field(default="hq-default-cluster")
    mode: ExecutionMode = Field(default=ExecutionMode.DEVELOPMENT)
    csp_provider: CspProvider = Field(default=CspProvider.ONPREM)
    free_tier: FreeTierProfileConfig = Field(default_factory=FreeTierProfileConfig)


class HexaqueueConfig(HexastackConfig):
    """Typed configuration container managing Hexaqueue core and package sections.

    Notes/Architectural Intent:
        Extends HexastackConfig with typed accessor for HexaqueueCoreConfig.
    """

    def __init__(
        self,
        core: HexaqueueCoreConfig,
        sections: dict[str, BaseModel],
    ) -> None:
        """Initialize HexaqueueConfig.

        Args:
            core: HexaqueueCoreConfig instance.
            sections: Dictionary of package configuration section models.
        """
        super().__init__(core=core, sections=sections)
        self._hexaqueue_core: HexaqueueCoreConfig = core

    @property
    def core(self) -> HexaqueueCoreConfig:
        """Retrieve typed HexaqueueCoreConfig instance."""
        return self._hexaqueue_core

    def get_section[T: BaseModel](self, section_name: str, expected_type: type[T]) -> T:
        """Retrieve a package configuration section with type validation.

        Args:
            section_name: Name of the configuration section.
            expected_type: Expected Pydantic model subclass.

        Returns:
            The requested section model instance.

        Raises:
            HexaqueueConfigError: If section is missing or fails type validation.
        """
        try:
            return super().get_section(section_name, expected_type)
        except Exception as err:
            raise HexaqueueConfigError(str(err)) from err


__all__ = [
    "CspProvider",
    "ExecutionMode",
    "FreeTierProfileConfig",
    "HexaqueueConfig",
    "HexaqueueConfigError",
    "HexaqueueCoreConfig",
]
