"""Domain configuration models for hexaqueue_scanner.

Notes/Architectural Intent:
    Encapsulates tuning and networking parameters for both software-managed
    antivirus daemons (ClamAV and YARA) and cloud provider-native deference
    (AWS GuardDuty Malware Protection for S3 and Azure Defender for Storage).
"""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClamAvConfig(BaseModel):
    """Configuration for local or containerized ClamAV daemon connectivity.

    Args:
        socket_path: Path to clamd UNIX domain socket (defaults to standard Linux socket).
        host: Hostname or IP if connecting via TCP instead of UNIX socket.
        port: TCP port if connecting via TCP (defaults to 3310 if host is set).
        timeout_seconds: Socket connect and communication timeout ceiling.
        chunk_size_bytes: Size of chunk buffers streamed over zINSTREAM (defaults to 256 KB).
        max_stream_bytes: Maximum total bytes streamed before aborting (defaults to 100 MB).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_size_bytes: int = Field(
        default=262144, ge=1024, description="Chunk buffer size in bytes for streaming"
    )
    host: str | None = Field(default=None, description="TCP host address for clamd")
    max_stream_bytes: int = Field(
        default=104857600, ge=1024, description="Max stream byte limit"
    )
    port: int | None = Field(
        default=None, ge=1, le=65535, description="TCP port for clamd"
    )
    socket_path: str | None = Field(
        default="/var/run/clamav/clamd.ctl",
        description="Path to UNIX domain socket",
    )
    timeout_seconds: float = Field(
        default=30.0, gt=0.0, description="Socket timeout in seconds"
    )

    @model_validator(mode="after")
    def validate_connection_target(self) -> Self:
        """Ensure either socket_path or host is provided."""
        if not self.socket_path and not self.host:
            msg = "Either socket_path or host must be specified for ClamAV connection"
            raise ValueError(msg)
        return self


class YaraRuleConfig(BaseModel):
    """Configuration for compiled YARA signature and heuristic rule matching.

    Args:
        rule_paths: List of file system paths to .yar or compiled rule files.
        inline_rules: List of raw YARA rule string declarations.
        timeout_seconds: Maximum rule evaluation duration per file.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    inline_rules: list[str] = Field(
        default_factory=list, description="Inline raw YARA rule declarations"
    )
    rule_paths: list[str] = Field(
        default_factory=list, description="Filesystem paths to YARA rule files"
    )
    timeout_seconds: float = Field(
        default=30.0, gt=0.0, description="Rule evaluation timeout in seconds"
    )


class CloudDeferenceConfig(BaseModel):
    """Configuration for Provider-Native Deference security inspection.

    Args:
        aws_guardduty_enabled: Whether to inspect S3 GuardDuty malware protection tags.
        aws_tag_key: The S3 tag key holding scan verdict (default: GuardDutyMalwareScanStatus).
        aws_clean_tag_values: Tag values indicating clean status (default: ['NO_THREATS_FOUND']).
        aws_threat_tag_values: Tag values indicating detected threat (default: ['THREATS_FOUND']).
        azure_defender_enabled: Whether to inspect Azure Blob Defender tags.
        azure_tag_key: The Azure Blob Index tag key (default: 'Malware Scanning scan result').
        azure_clean_tag_values: Tag values indicating clean status (default: ['No threats found']).
        azure_threat_tag_values: Tag values indicating malware (default: ['Malware found']).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    aws_clean_tag_values: list[str] = Field(
        default_factory=lambda: ["NO_THREATS_FOUND"],
        description="S3 tag values denoting clean bundle",
    )
    aws_guardduty_enabled: bool = Field(
        default=True, description="Enable AWS GuardDuty S3 tag inspection"
    )
    aws_tag_key: str = Field(
        default="GuardDutyMalwareScanStatus",
        description="S3 object tag key for GuardDuty status",
    )
    aws_threat_tag_values: list[str] = Field(
        default_factory=lambda: ["THREATS_FOUND"],
        description="S3 tag values denoting malware threat",
    )
    azure_clean_tag_values: list[str] = Field(
        default_factory=lambda: ["No threats found"],
        description="Blob tag values denoting clean bundle",
    )
    azure_defender_enabled: bool = Field(
        default=True, description="Enable Azure Defender for Storage inspection"
    )
    azure_tag_key: str = Field(
        default="Malware Scanning scan result",
        description="Azure Blob Index tag key for Defender status",
    )
    azure_threat_tag_values: list[str] = Field(
        default_factory=lambda: ["Malware found"],
        description="Blob tag values denoting malware threat",
    )


class ScannerConfig(BaseModel):
    """Aggregate configuration for the hexaqueue-scanner security daemon.

    Args:
        clamav: ClamAV daemon connectivity settings.
        yara: YARA rule and signature matching settings.
        cloud: Provider-Native Deference configuration for AWS and Azure.
        quarantine_on_threat: If True, contaminated bundles enter QUARANTINED state; if False, REJECTED.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    clamav: ClamAvConfig = Field(
        default_factory=ClamAvConfig, description="ClamAV daemon configuration"
    )
    cloud: CloudDeferenceConfig = Field(
        default_factory=CloudDeferenceConfig,
        description="Provider-Native Deference settings",
    )
    quarantine_on_threat: bool = Field(
        default=True,
        description="If True transition to QUARANTINED, else REJECTED upon threat",
    )
    yara: YaraRuleConfig = Field(
        default_factory=YaraRuleConfig, description="YARA rule engine configuration"
    )


__all__ = [
    "ClamAvConfig",
    "CloudDeferenceConfig",
    "ScannerConfig",
    "YaraRuleConfig",
]
