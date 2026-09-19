"""Adapters package for hexaqueue-scanner."""

from hexaqueue_scanner.adapters.clamav import ClamAvDaemonAdapter
from hexaqueue_scanner.adapters.composite import CompositeQuarantineScannerAdapter
from hexaqueue_scanner.adapters.deference import (
    AwsGuardDutyQuarantineAdapter,
    AzureDefenderQuarantineAdapter,
    PassThroughSecurityQuarantineAdapter,
)
from hexaqueue_scanner.adapters.yara import YaraRuleScannerAdapter

__all__ = [
    "AwsGuardDutyQuarantineAdapter",
    "AzureDefenderQuarantineAdapter",
    "ClamAvDaemonAdapter",
    "CompositeQuarantineScannerAdapter",
    "PassThroughSecurityQuarantineAdapter",
    "YaraRuleScannerAdapter",
]
