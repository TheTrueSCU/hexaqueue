"""Unit tests for TelemetryEmitterPort interface contracts."""

from collections.abc import AsyncIterator

import pytest

from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse
from hexaqueue_worker.ports.telemetry import TelemetryEmitterPort


class DummyTelemetryEmitter(TelemetryEmitterPort):
    """Test double implementing TelemetryEmitterPort."""

    def __init__(self) -> None:
        self.emitted: list[NodeTelemetryPulse] = []

    async def emit_pulse(self, pulse: NodeTelemetryPulse) -> None:
        """Record emitted pulse."""
        self.emitted.append(pulse)

    async def subscribe_pulses(
        self, worker_id: str | None = None
    ) -> AsyncIterator[NodeTelemetryPulse]:
        """Yield recorded pulses."""
        for p in self.emitted:
            if worker_id is None or p.worker_id == worker_id:
                yield p


@pytest.mark.asyncio
async def test_dummy_telemetry_emitter_contract() -> None:
    """Verify TelemetryEmitterPort dummy implementation fulfills contract."""
    emitter = DummyTelemetryEmitter()
    pulse = NodeTelemetryPulse(
        worker_id="worker-test",
        memory_used_mb=2048,
        memory_total_mb=8192,
        scratch_used_mb=1024,
        scratch_total_mb=10240,
    )
    await emitter.emit_pulse(pulse)
    pulses = [p async for p in emitter.subscribe_pulses("worker-test")]
    pulses_len = len(pulses)
    assert pulses_len == 1
    w_id = pulses[0].worker_id
    assert w_id == "worker-test"
