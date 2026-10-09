"""Domain models for worker and node telemetry pulses.

Notes/Architectural Intent:
    Re-exports telemetry models from hexaqueue-core for worker execution,
    maintaining backward compatibility while adhering to hexagonal isolation layers.
"""

from hexaqueue_core.domain.telemetry import GpuTelemetry, NodeTelemetryPulse

__all__ = [
    "GpuTelemetry",
    "NodeTelemetryPulse",
]
