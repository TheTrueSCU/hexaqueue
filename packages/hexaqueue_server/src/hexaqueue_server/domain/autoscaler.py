"""Budget and queue-depth driven instance pool autoscaler.

Notes/Architectural Intent:
    Orchestrates dynamic capacity scaling across cloud instance pools.
    Evaluates pending job queue depth by capability tag, enforces budget
    limits via BudgetAccountingPort, tracks scale-up stall circuit breaking,
    and scales idle pools down to zero.
"""

import contextlib
import time
from typing import Any

from hexastack_core.adapters.circuit_breaker.in_memory import InMemoryCircuitBreaker
from hexastack_core.ports.circuit_breaker import CircuitBreakerPort, CircuitState

from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.pool import (
    AutoscalerDecision,
    InstancePoolState,
    PoolScaleRequest,
)
from hexaqueue_core.ports.budget import BudgetAccountingPort
from hexaqueue_core.ports.pool import InstancePoolGovernorPort


class BudgetAwareInstancePoolAutoscaler:
    """Autoscaler governing instance pool capacity based on queue depth and spend caps."""

    def __init__(
        self,
        governors: dict[str, InstancePoolGovernorPort] | None = None,
        budget_port: BudgetAccountingPort | None = None,
        min_budget_reserve: float = 1.0,
        scale_up_grace_seconds: float = 180.0,
        circuit_cooldown_seconds: float = 300.0,
        circuit_breaker: CircuitBreakerPort | None = None,
    ) -> None:
        """Initialize autoscaler engine.

        Args:
            governors: Mapping of pool_id to its corresponding InstancePoolGovernorPort.
            budget_port: Optional BudgetAccountingPort for credit balance checks.
            min_budget_reserve: Minimum available credits required before scale-out.
            scale_up_grace_seconds: Seconds allowed for a scaled-out pool with 0 ready
                nodes to boot at least one instance before tripping the circuit breaker.
            circuit_cooldown_seconds: Base cooldown seconds before retrying scale-out
                after a circuit breaker trip.
            circuit_breaker: Optional Hexastack ``CircuitBreakerPort`` implementation
                (defaults to ``InMemoryCircuitBreaker(failure_threshold=1,
                recovery_timeout_seconds=circuit_cooldown_seconds)``).
        """
        self._governors = governors or {}
        self._budget_port = budget_port
        self._min_budget_reserve = min_budget_reserve
        self._scale_up_grace_seconds = scale_up_grace_seconds
        self._circuit_cooldown_seconds = circuit_cooldown_seconds
        self._circuit_breaker: CircuitBreakerPort = (
            circuit_breaker
            or InMemoryCircuitBreaker(
                failure_threshold=1,
                recovery_timeout_seconds=circuit_cooldown_seconds,
            )
        )
        self._scale_up_started_at: dict[str, float] = {}
        self._circuit_tripped_until: dict[str, float] = {}
        self._circuit_reasons: dict[str, str] = {}
        self._circuit_trip_counts: dict[str, int] = {}

    def get_pool_circuit_status(
        self, pool_id: str, now: float | None = None
    ) -> dict[str, Any]:
        """Return current circuit-breaker state for a governed pool.

        Args:
            pool_id: Target pool identifier.
            now: Optional monotonic/epoch timestamp override.

        Returns:
            Dictionary with ``state`` (``"CLOSED"``, ``"OPEN"``, or ``"HALF_OPEN"``),
            ``reason``, ``retry_after_seconds``, and ``trip_count``.
        """
        ts = time.time() if now is None else now
        until = self._circuit_tripped_until.get(pool_id, 0.0)
        cb_state = self._circuit_breaker.state(pool_id)
        if until > ts or cb_state == CircuitState.OPEN:
            return {
                "state": "OPEN",
                "reason": self._circuit_reasons.get(
                    pool_id, "Pool scale-up circuit breaker tripped"
                ),
                "retry_after_seconds": round(max(0.0, until - ts), 1),
                "trip_count": self._circuit_trip_counts.get(pool_id, 1),
            }
        state_label = "HALF_OPEN" if cb_state == CircuitState.HALF_OPEN else "CLOSED"
        return {
            "state": state_label,
            "reason": None,
            "retry_after_seconds": 0.0,
            "trip_count": self._circuit_trip_counts.get(pool_id, 0),
        }

    def trip_circuit(
        self,
        pool_id: str,
        reason: str,
        *,
        now: float | None = None,
    ) -> None:
        """Trip the scale-up circuit breaker for ``pool_id`` via CircuitBreakerPort."""
        ts = time.time() if now is None else now
        self._circuit_breaker.record_failure(pool_id, HexaqueueError(reason))
        trips = self._circuit_trip_counts.get(pool_id, 0) + 1
        self._circuit_trip_counts[pool_id] = trips
        backoff = min(3600.0, self._circuit_cooldown_seconds * (2 ** (trips - 1)))
        self._circuit_tripped_until[pool_id] = ts + backoff
        self._circuit_reasons[pool_id] = reason
        self._scale_up_started_at.pop(pool_id, None)

    def reset_circuit(self, pool_id: str) -> None:
        """Reset circuit breaker state via CircuitBreakerPort once pool recovers."""
        self._circuit_breaker.record_success(pool_id)
        self._circuit_breaker.reset(pool_id)
        self._circuit_tripped_until.pop(pool_id, None)
        self._circuit_reasons.pop(pool_id, None)
        self._circuit_trip_counts.pop(pool_id, None)
        self._scale_up_started_at.pop(pool_id, None)

    def register_governor(
        self, pool_id: str, governor: InstancePoolGovernorPort
    ) -> None:
        """Register a pool governor adapter.

        Args:
            pool_id: Unique pool identifier.
            governor: InstancePoolGovernorPort implementation.
        """
        self._governors[pool_id] = governor

    def evaluate_scaling(
        self,
        pool: InstancePoolState,
        pending_jobs: int,
        running_jobs: int = 0,
        available_budget: float | None = None,
    ) -> AutoscalerDecision:
        """Compute an autoscaling decision based on queue backlog and available budget.

        Args:
            pool: Current pool state snapshot.
            pending_jobs: Number of queued jobs matching pool capability tags.
            running_jobs: Number of currently executing jobs in this pool.
            available_budget: Available credits from tenant account, if known.

        Returns:
            AutoscalerDecision with action, target nodes, and justification.
        """
        if pending_jobs > 0:
            if pool.max_nodes <= 0 and pool.current_nodes > 0:
                return AutoscalerDecision(
                    pool_id=pool.pool_id,
                    action="SCALE_DOWN",
                    current_nodes=pool.current_nodes,
                    target_nodes=0,
                    pending_jobs=pending_jobs,
                    reason="Pool ceiling is 0 (HEXAQUEUE_OCI_MAX_POOL_SIZE=0); scaling down to 0",
                )
            if pool.current_nodes >= pool.max_nodes:
                return AutoscalerDecision(
                    pool_id=pool.pool_id,
                    action="NOOP",
                    current_nodes=pool.current_nodes,
                    target_nodes=pool.current_nodes,
                    pending_jobs=pending_jobs,
                    reason=f"Pool at maximum capacity ceiling ({pool.max_nodes})",
                )

            if (
                available_budget is not None
                and available_budget < self._min_budget_reserve
            ):
                return AutoscalerDecision(
                    pool_id=pool.pool_id,
                    action="THROTTLED_BUDGET",
                    current_nodes=pool.current_nodes,
                    target_nodes=pool.current_nodes,
                    pending_jobs=pending_jobs,
                    reason=(
                        f"Scale-up throttled: available budget {available_budget:.2f} "
                        f"below required reserve {self._min_budget_reserve:.2f}"
                    ),
                )

            target = min(
                pool.max_nodes, max(pool.min_nodes, pool.current_nodes + pending_jobs)
            )
            return AutoscalerDecision(
                pool_id=pool.pool_id,
                action="SCALE_UP",
                current_nodes=pool.current_nodes,
                target_nodes=target,
                pending_jobs=pending_jobs,
                reason=f"Scale-up requested for {pending_jobs} queued jobs",
            )

        if running_jobs == 0 and pool.current_nodes > pool.min_nodes:
            return AutoscalerDecision(
                pool_id=pool.pool_id,
                action="SCALE_DOWN",
                current_nodes=pool.current_nodes,
                target_nodes=pool.min_nodes,
                pending_jobs=0,
                reason=f"Queue drained and idle, scaling down to floor ({pool.min_nodes})",
            )

        return AutoscalerDecision(
            pool_id=pool.pool_id,
            action="NOOP",
            current_nodes=pool.current_nodes,
            target_nodes=pool.current_nodes,
            pending_jobs=0,
            reason="Pool capacity matches current demand",
        )

    async def reconcile_pool(
        self,
        pool_id: str,
        pending_jobs: int,
        running_jobs: int = 0,
        tenant_id: str | None = None,
        now: float | None = None,
    ) -> AutoscalerDecision:
        """Evaluate and apply scaling decision to the target pool governor.

        Args:
            pool_id: Unique pool identifier.
            pending_jobs: Number of queued jobs matching pool capability tags.
            running_jobs: Number of currently executing jobs in this pool.
            tenant_id: Optional tenant identifier for budget accounting checks.
            now: Optional epoch timestamp override for deterministic testing.

        Returns:
            Applied AutoscalerDecision.

        Raises:
            HexaqueueError: If no governor is registered for the specified pool_id.
        """
        governor = self._governors.get(pool_id)
        if governor is None:
            msg = f"No governor registered for pool '{pool_id}'"
            raise HexaqueueError(msg)

        ts = time.time() if now is None else now
        pool_state = await governor.get_pool_state(pool_id)

        if pool_state.ready_nodes > 0:
            self.reset_circuit(pool_id)
        elif pool_state.desired_nodes > 0 and pool_state.ready_nodes == 0:
            started = self._scale_up_started_at.setdefault(pool_id, ts)
            if ts - started >= self._scale_up_grace_seconds:
                stall_reason = (
                    f"Pool scale-up stalled for {ts - started:.0f}s with "
                    f"desired={pool_state.desired_nodes}, ready=0; tripping circuit breaker and scaling to 0"
                )
                self.trip_circuit(pool_id, stall_reason, now=ts)
                with contextlib.suppress(Exception):
                    await governor.scale_pool(
                        PoolScaleRequest(
                            pool_id=pool_id,
                            target_nodes=pool_state.min_nodes,
                            reason=stall_reason,
                        )
                    )
                return AutoscalerDecision(
                    pool_id=pool_id,
                    action="SCALE_DOWN",
                    current_nodes=pool_state.current_nodes,
                    target_nodes=pool_state.min_nodes,
                    pending_jobs=pending_jobs,
                    reason=stall_reason,
                )

        circuit = self.get_pool_circuit_status(pool_id, now=ts)
        if circuit["state"] == "OPEN" and pending_jobs > 0:
            return AutoscalerDecision(
                pool_id=pool_id,
                action="NOOP",
                current_nodes=pool_state.current_nodes,
                target_nodes=pool_state.min_nodes,
                pending_jobs=pending_jobs,
                reason=f"Circuit breaker OPEN ({circuit['reason']}); retry in {circuit['retry_after_seconds']}s",
            )

        available_budget: float | None = None
        if self._budget_port is not None and tenant_id is not None:
            account = await self._budget_port.get_account(tenant_id)
            available_budget = account.available_balance

        decision = self.evaluate_scaling(
            pool=pool_state,
            pending_jobs=pending_jobs,
            running_jobs=running_jobs,
            available_budget=available_budget,
        )

        if decision.action in ("SCALE_UP", "SCALE_DOWN"):
            try:
                await governor.scale_pool(
                    PoolScaleRequest(
                        pool_id=pool_id,
                        target_nodes=decision.target_nodes,
                        reason=decision.reason,
                    )
                )
                if decision.action == "SCALE_UP" and pool_state.ready_nodes == 0:
                    self._scale_up_started_at.setdefault(pool_id, ts)
                elif decision.action == "SCALE_DOWN":
                    self._scale_up_started_at.pop(pool_id, None)
            except Exception as exc:
                err_str = str(exc)
                if any(
                    tok in err_str.lower()
                    for tok in (
                        "out of host capacity",
                        "limitexceeded",
                        "quota",
                        "outofcapacity",
                    )
                ):
                    self.trip_circuit(
                        pool_id,
                        f"CSP capacity exhausted during scale-up: {err_str}",
                        now=ts,
                    )
                    return AutoscalerDecision(
                        pool_id=pool_id,
                        action="NOOP",
                        current_nodes=pool_state.current_nodes,
                        target_nodes=pool_state.current_nodes,
                        pending_jobs=pending_jobs,
                        reason=f"Circuit breaker tripped: {err_str}",
                    )
                raise

        return decision
