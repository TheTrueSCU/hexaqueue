"""Budget and queue-depth driven instance pool autoscaler.

Notes/Architectural Intent:
    Orchestrates dynamic capacity scaling across cloud instance pools.
    Evaluates pending job queue depth by capability tag, enforces budget
    limits via BudgetAccountingPort, tracks scale-up stall circuit breaking,
    and scales idle pools down to zero.
"""

import contextlib
import os
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from hexastack_core.adapters.circuit_breaker.in_memory import InMemoryCircuitBreaker
from hexastack_core.ports.circuit_breaker import CircuitBreakerPort, CircuitState
from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.pool import (
    AutoscalerDecision,
    InstancePoolState,
    PoolScaleRequest,
)
from hexaqueue_core.ports.budget import BudgetAccountingPort
from hexaqueue_core.ports.pool import InstancePoolGovernorPort


class BudgetStrategyMode(StrEnum):
    """Pluggable budget strategy governing elastic burst pool capacity.

    Notes/Architectural Intent:
        Lets operators switch burst-pool budget governance as tenancy
        circumstances change, without code changes:

        - ``FREE_TIER_ONLY``: Burst ceiling locked to 0 ($0.00 spend); only
          Always-Free baseline workers run.
        - ``LINEAR_CREDIT_PACING``: Meters remaining credits evenly across the
          days left before ``expiry_time``; drops to 0 nodes upon expiry.
        - ``FRONT_LOADED_CREDITS``: Allows the full ``hard_ceiling`` while
          spendable credits remain above the reserve and before expiry
          (useful for pre-release sprints).
        - ``FIXED_DAILY_CAP``: Enforces ``daily_cap_usd`` regardless of any
          credit expiry (e.g. steady-state Pay-As-You-Go).
        - ``UNCONSTRAINED``: Bypasses pacing; defers to ``pool.max_nodes`` and
          ``BudgetAccountingPort``.
    """

    FIXED_DAILY_CAP = "FIXED_DAILY_CAP"
    FREE_TIER_ONLY = "FREE_TIER_ONLY"
    FRONT_LOADED_CREDITS = "FRONT_LOADED_CREDITS"
    LINEAR_CREDIT_PACING = "LINEAR_CREDIT_PACING"
    UNCONSTRAINED = "UNCONSTRAINED"


def _parse_utc(raw: str) -> datetime | None:
    """Parse an ISO-8601 timestamp (accepting a trailing ``Z``) as UTC."""
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class CreditPacingPolicy(BaseModel):
    """Budget strategy policy metering burst-pool spend.

    Args:
        strategy: Active ``BudgetStrategyMode``.
        total_credits_usd: Total credit allocation in USD (e.g. 300.0).
        spent_credits_usd: Cumulative credits consumed to date in USD.
        reserve_credits_usd: Safety buffer never spent on burst capacity.
        daily_cap_usd: Daily spend cap used by ``FIXED_DAILY_CAP`` (and as the
            fallback for ``LINEAR_CREDIT_PACING`` when no expiry is set).
        hourly_cost_per_node_usd: Estimated hourly burn rate per burst node.
        start_time: Optional credit window start timestamp in UTC.
        expiry_time: Optional credit window expiration timestamp in UTC.

    Notes/Architectural Intent:
        Pure domain value object (no I/O beyond ``from_env``); the autoscaler
        consults ``recommended_max_nodes`` to clamp the effective pool ceiling,
        and ``BudgetAwareInstancePoolAutoscaler.set_credit_pacing`` allows the
        strategy to be swapped at runtime.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    daily_cap_usd: float = Field(
        default=25.0, ge=0.0, description="Daily USD spend cap"
    )
    expiry_time: datetime | None = Field(
        default=None, description="Credit expiration timestamp in UTC"
    )
    strategy: BudgetStrategyMode = Field(
        default=BudgetStrategyMode.LINEAR_CREDIT_PACING,
        description="Active budget strategy",
    )
    hourly_cost_per_node_usd: float = Field(
        default=0.046, gt=0.0, description="Hourly USD burn rate per worker node"
    )
    reserve_credits_usd: float = Field(
        default=15.0, ge=0.0, description="Safety reserve in USD"
    )
    spent_credits_usd: float = Field(
        default=0.0, ge=0.0, description="Cumulative spend to date in USD"
    )
    start_time: datetime | None = Field(
        default=None, description="Credit window start timestamp in UTC"
    )
    total_credits_usd: float = Field(
        default=300.0, gt=0.0, description="Total credit allocation in USD"
    )

    @classmethod
    def from_env(cls) -> "CreditPacingPolicy | None":
        """Construct a CreditPacingPolicy from environment variables if configured.

        Reads ``HEXAQUEUE_BUDGET_STRATEGY``, ``HEXAQUEUE_CREDIT_EXPIRY_DATE``,
        ``HEXAQUEUE_CREDIT_START_DATE``, ``HEXAQUEUE_DAILY_CAP_USD``,
        ``HEXAQUEUE_CREDIT_TOTAL_USD``, ``HEXAQUEUE_CREDIT_SPENT_USD``,
        ``HEXAQUEUE_CREDIT_RESERVE_USD``, and ``HEXAQUEUE_WORKER_HOURLY_USD``.

        Returns:
            Configured CreditPacingPolicy, or None if none of
            ``HEXAQUEUE_BUDGET_STRATEGY``, ``HEXAQUEUE_CREDIT_EXPIRY_DATE``, or
            ``HEXAQUEUE_DAILY_CAP_USD`` are set.

        Raises:
            ValueError: If ``HEXAQUEUE_BUDGET_STRATEGY`` is not a valid
                ``BudgetStrategyMode`` or timestamps/numeric values are malformed.

        Notes/Architectural Intent:
            Allows switching between promotional credit metering, strict
            Always-Free operation, and steady-state PAYG daily spend caps pure
            via configuration without code changes.
        """
        raw_strategy = os.environ.get("HEXAQUEUE_BUDGET_STRATEGY", "").strip()
        raw_expiry = os.environ.get("HEXAQUEUE_CREDIT_EXPIRY_DATE", "").strip()
        raw_daily_cap = os.environ.get("HEXAQUEUE_DAILY_CAP_USD", "").strip()
        if not raw_strategy and not raw_expiry and not raw_daily_cap:
            return None

        if raw_strategy:
            strategy = BudgetStrategyMode(raw_strategy.upper())
        elif raw_expiry:
            strategy = BudgetStrategyMode.LINEAR_CREDIT_PACING
        else:
            strategy = BudgetStrategyMode.FIXED_DAILY_CAP

        expiry_dt = _parse_utc(raw_expiry)
        raw_start = os.environ.get("HEXAQUEUE_CREDIT_START_DATE", "").strip()
        start_dt = _parse_utc(raw_start)
        if expiry_dt is not None and start_dt is None:
            start_dt = datetime.fromtimestamp(
                expiry_dt.timestamp() - 30 * 86400.0, tz=UTC
            )

        return cls(
            strategy=strategy,
            daily_cap_usd=float(raw_daily_cap or "25.0"),
            total_credits_usd=float(
                os.environ.get("HEXAQUEUE_CREDIT_TOTAL_USD", "300.0") or "300.0"
            ),
            spent_credits_usd=float(
                os.environ.get("HEXAQUEUE_CREDIT_SPENT_USD", "0.0") or "0.0"
            ),
            reserve_credits_usd=float(
                os.environ.get("HEXAQUEUE_CREDIT_RESERVE_USD", "15.0") or "15.0"
            ),
            hourly_cost_per_node_usd=float(
                os.environ.get("HEXAQUEUE_WORKER_HOURLY_USD", "0.046") or "0.046"
            ),
            start_time=start_dt,
            expiry_time=expiry_dt,
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        """Return True if a configured credit expiry timestamp has passed.

        Args:
            now: Optional evaluation timestamp in UTC.

        Returns:
            True when ``expiry_time`` is set and ``now >= expiry_time``.
        """
        if self.expiry_time is None:
            return False
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        expiry = (
            self.expiry_time
            if self.expiry_time.tzinfo is not None
            else self.expiry_time.replace(tzinfo=UTC)
        )
        return current >= expiry

    def spendable_remaining_usd(self) -> float:
        """Return remaining credits above the safety reserve."""
        return max(
            0.0,
            self.total_credits_usd - self.spent_credits_usd - self.reserve_credits_usd,
        )

    def daily_allowance_usd(self, now: datetime | None = None) -> float:
        """Return daily spend allowance according to the active budget strategy.

        Args:
            now: Optional evaluation timestamp in UTC.

        Returns:
            Daily USD allowance for burst worker provisioning.
        """
        if self.strategy == BudgetStrategyMode.FREE_TIER_ONLY:
            return 0.0
        if self.strategy == BudgetStrategyMode.FIXED_DAILY_CAP:
            return round(self.daily_cap_usd, 2)
        if self.strategy == BudgetStrategyMode.UNCONSTRAINED:
            return round(max(self.total_credits_usd, self.daily_cap_usd), 2)

        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        if self.is_expired(current):
            return 0.0

        if self.strategy == BudgetStrategyMode.FRONT_LOADED_CREDITS:
            return round(self.spendable_remaining_usd(), 2)

        if self.expiry_time is None:
            return round(min(self.daily_cap_usd, self.spendable_remaining_usd()), 2)

        expiry = (
            self.expiry_time
            if self.expiry_time.tzinfo is not None
            else self.expiry_time.replace(tzinfo=UTC)
        )
        remaining_days = max(1.0 / 24.0, (expiry - current).total_seconds() / 86400.0)
        return round(self.spendable_remaining_usd() / remaining_days, 2)

    def recommended_max_nodes(
        self,
        hard_ceiling: int = 10,
        assumed_active_hours_per_day: float = 4.0,
        now: datetime | None = None,
    ) -> int:
        """Compute maximum burst worker nodes permitted by the active budget strategy.

        Args:
            hard_ceiling: Upper bound node ceiling from pool configuration.
            assumed_active_hours_per_day: Expected daily burst active hours.
            now: Optional evaluation timestamp in UTC.

        Returns:
            Clamped maximum node count (0 when restricted, expired, or reserve exhausted).
        """
        if hard_ceiling <= 0 or self.strategy == BudgetStrategyMode.FREE_TIER_ONLY:
            return 0
        if self.strategy == BudgetStrategyMode.UNCONSTRAINED:
            return hard_ceiling
        if self.strategy == BudgetStrategyMode.FRONT_LOADED_CREDITS:
            if self.is_expired(now) or self.spendable_remaining_usd() <= 0.0:
                return 0
            return hard_ceiling

        allowance = self.daily_allowance_usd(now)
        if allowance <= 0.0:
            return 0
        daily_cost_per_node = self.hourly_cost_per_node_usd * max(
            0.25, assumed_active_hours_per_day
        )
        paced_nodes = int(round(allowance / daily_cost_per_node, 9))
        return max(0, min(hard_ceiling, paced_nodes))


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
        credit_pacing: CreditPacingPolicy | None = None,
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
            credit_pacing: Optional ``CreditPacingPolicy`` metering promotional credits
                over their remaining lifetime and locking burst pools to 0 upon expiry.
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
        self._credit_pacing = (
            credit_pacing
            if credit_pacing is not None
            else CreditPacingPolicy.from_env()
        )
        self._scale_up_started_at: dict[str, float] = {}
        self._circuit_tripped_until: dict[str, float] = {}
        self._circuit_reasons: dict[str, str] = {}
        self._circuit_trip_counts: dict[str, int] = {}

    @property
    def credit_pacing(self) -> CreditPacingPolicy | None:
        """Return the active credit pacing policy, if configured."""
        return self._credit_pacing

    def set_credit_pacing(self, policy: CreditPacingPolicy | None) -> None:
        """Replace the active credit pacing policy and budget strategy at runtime.

        Args:
            policy: New ``CreditPacingPolicy`` instance, or ``None`` to disable
                credit pacing and defer solely to pool limits and ``BudgetAccountingPort``.

        Notes/Architectural Intent:
            Allows live controller APIs and operators to swap between
            ``BudgetStrategyMode`` strategies (e.g., ``LINEAR_CREDIT_PACING``,
            ``FREE_TIER_ONLY``, ``FIXED_DAILY_CAP``) without restarting the daemon.
        """
        self._credit_pacing = policy

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
            effective_max = pool.max_nodes
            if self._credit_pacing is not None:
                paced_max = self._credit_pacing.recommended_max_nodes(
                    hard_ceiling=pool.max_nodes
                )
                if paced_max <= 0:
                    strategy_label = self._credit_pacing.strategy.value
                    if pool.current_nodes > 0:
                        return AutoscalerDecision(
                            pool_id=pool.pool_id,
                            action="SCALE_DOWN",
                            current_nodes=pool.current_nodes,
                            target_nodes=0,
                            pending_jobs=pending_jobs,
                            reason=(
                                f"Budget strategy {strategy_label} allows 0 nodes "
                                "(window expired, free-tier lock, or reserve reached); "
                                "scaling burst pool to 0"
                            ),
                        )
                    return AutoscalerDecision(
                        pool_id=pool.pool_id,
                        action="THROTTLED_BUDGET",
                        current_nodes=pool.current_nodes,
                        target_nodes=0,
                        pending_jobs=pending_jobs,
                        reason=(
                            f"Scale-up throttled by budget strategy {strategy_label}: "
                            "burst ceiling is 0"
                        ),
                    )
                effective_max = min(effective_max, paced_max)

            if effective_max <= 0 and pool.current_nodes > 0:
                return AutoscalerDecision(
                    pool_id=pool.pool_id,
                    action="SCALE_DOWN",
                    current_nodes=pool.current_nodes,
                    target_nodes=0,
                    pending_jobs=pending_jobs,
                    reason="Pool ceiling is 0 (HEXAQUEUE_OCI_MAX_POOL_SIZE=0); scaling down to 0",
                )
            if pool.current_nodes >= effective_max:
                return AutoscalerDecision(
                    pool_id=pool.pool_id,
                    action="NOOP",
                    current_nodes=pool.current_nodes,
                    target_nodes=pool.current_nodes,
                    pending_jobs=pending_jobs,
                    reason=f"Pool at maximum capacity ceiling ({effective_max})",
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
                effective_max, max(pool.min_nodes, pool.current_nodes + pending_jobs)
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
        pool_state: InstancePoolState | None = None,
    ) -> AutoscalerDecision:
        """Evaluate and apply scaling decision to the target pool governor.

        Args:
            pool_id: Unique pool identifier.
            pending_jobs: Number of queued jobs matching pool capability tags.
            running_jobs: Number of currently executing jobs in this pool.
            tenant_id: Optional tenant identifier for budget accounting checks.
            now: Optional epoch timestamp override for deterministic testing.
            pool_state: Optional pre-fetched InstancePoolState snapshot to avoid redundant CSP calls.

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
        resolved_state = (
            await governor.get_pool_state(pool_id) if pool_state is None else pool_state
        )

        if resolved_state.ready_nodes > 0:
            self.reset_circuit(pool_id)
        elif resolved_state.desired_nodes > 0 and resolved_state.ready_nodes == 0:
            started = self._scale_up_started_at.setdefault(pool_id, ts)
            if ts - started >= self._scale_up_grace_seconds:
                stall_reason = (
                    f"Pool scale-up stalled for {ts - started:.0f}s with "
                    f"desired={resolved_state.desired_nodes}, ready=0; tripping circuit breaker and scaling to 0"
                )
                self.trip_circuit(pool_id, stall_reason, now=ts)
                with contextlib.suppress(Exception):
                    await governor.scale_pool(
                        PoolScaleRequest(
                            pool_id=pool_id,
                            target_nodes=resolved_state.min_nodes,
                            reason=stall_reason,
                        )
                    )
                return AutoscalerDecision(
                    pool_id=pool_id,
                    action="SCALE_DOWN",
                    current_nodes=resolved_state.current_nodes,
                    target_nodes=resolved_state.min_nodes,
                    pending_jobs=pending_jobs,
                    reason=stall_reason,
                )

        circuit = self.get_pool_circuit_status(pool_id, now=ts)
        if circuit["state"] == "OPEN" and pending_jobs > 0:
            return AutoscalerDecision(
                pool_id=pool_id,
                action="NOOP",
                current_nodes=resolved_state.current_nodes,
                target_nodes=resolved_state.min_nodes,
                pending_jobs=pending_jobs,
                reason=f"Circuit breaker OPEN ({circuit['reason']}); retry in {circuit['retry_after_seconds']}s",
            )

        available_budget: float | None = None
        if self._budget_port is not None and tenant_id is not None:
            account = await self._budget_port.get_account(tenant_id)
            available_budget = account.available_balance

        decision = self.evaluate_scaling(
            pool=resolved_state,
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
                if decision.action == "SCALE_UP" and resolved_state.ready_nodes == 0:
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
                        current_nodes=resolved_state.current_nodes,
                        target_nodes=resolved_state.current_nodes,
                        pending_jobs=pending_jobs,
                        reason=f"Circuit breaker tripped: {err_str}",
                    )
                raise

        return decision

    def has_active_reconciliation_work(
        self,
        pool_ids: Sequence[str],
        now: float | None = None,
    ) -> bool:
        """Return True if any pool has an active scale-up or non-CLOSED circuit breaker.

        Args:
            pool_ids: Pool identifiers monitored by the reconciler.
            now: Optional epoch timestamp override for deterministic testing.

        Returns:
            True when periodic reconciliation should evaluate capacity recovery or stalls.
        """
        ts = time.time() if now is None else now
        for pid in pool_ids:
            if pid in self._scale_up_started_at:
                return True
            if self.get_pool_circuit_status(pid, now=ts)["state"] != "CLOSED":
                return True
        return False

    @staticmethod
    def _pool_capacity_contributed(
        decision: AutoscalerDecision,
        pool_state: InstancePoolState,
    ) -> int:
        """Compute node capacity supplied by one priority pool step."""
        if decision.action == "SCALE_DOWN":
            return 0
        if "tripped" in decision.reason.lower():
            return 0
        if (
            decision.action == "SCALE_UP"
            or pool_state.ready_nodes > 0
            or pool_state.desired_nodes > 0
        ):
            return max(decision.target_nodes, pool_state.ready_nodes)
        return 0

    async def _reconcile_priority_scale_down(
        self,
        pool_ids: Sequence[str],
        running_jobs: int,
        tenant_id: str | None,
        now: float | None,
    ) -> list[AutoscalerDecision]:
        """Scale down or sweep every registered priority pool when queue is empty."""
        decisions: list[AutoscalerDecision] = []
        for pid in pool_ids:
            if pid not in self._governors:
                continue
            try:
                dec = await self.reconcile_pool(
                    pool_id=pid,
                    pending_jobs=0,
                    running_jobs=running_jobs,
                    tenant_id=tenant_id,
                    now=now,
                )
            except Exception as exc:
                dec = AutoscalerDecision(
                    pool_id=pid,
                    action="NOOP",
                    current_nodes=0,
                    target_nodes=0,
                    pending_jobs=0,
                    reason=f"Pool evaluation error ({type(exc).__name__}): {exc}; continuing",
                )
            decisions.append(dec)
        return decisions

    async def _reconcile_priority_pool_step(
        self,
        pid: str,
        remaining: int,
        running_jobs: int,
        tenant_id: str | None,
        ts: float,
    ) -> tuple[AutoscalerDecision | None, int]:
        """Evaluate one pool in priority order and return decision plus new remaining backlog."""
        governor = self._governors.get(pid)
        if governor is None:
            return None, remaining

        circuit = self.get_pool_circuit_status(pid, now=ts)
        has_active_scale_up = pid in self._scale_up_started_at
        if circuit["state"] == "OPEN" and not has_active_scale_up:
            return (
                AutoscalerDecision(
                    pool_id=pid,
                    action="NOOP",
                    current_nodes=0,
                    target_nodes=0,
                    pending_jobs=remaining,
                    reason=f"Circuit breaker OPEN ({circuit['reason']}); retry in {circuit['retry_after_seconds']}s",
                ),
                remaining,
            )

        if not has_active_scale_up and remaining <= 0:
            return None, remaining

        pool_state = await governor.get_pool_state(pid)
        stalled_candidate = pool_state.desired_nodes > 0 and pool_state.ready_nodes == 0
        if circuit["state"] == "OPEN" and not stalled_candidate:
            return (
                AutoscalerDecision(
                    pool_id=pid,
                    action="NOOP",
                    current_nodes=pool_state.current_nodes,
                    target_nodes=pool_state.min_nodes,
                    pending_jobs=remaining,
                    reason=f"Circuit breaker OPEN ({circuit['reason']}); retry in {circuit['retry_after_seconds']}s",
                ),
                remaining,
            )

        if not stalled_candidate and remaining <= 0:
            return None, remaining

        if not stalled_candidate and pool_state.ready_nodes == 0:
            checker = getattr(governor, "check_pool_capacity", None)
            if callable(checker):
                has_cap = await checker(pid)
                if not has_cap:
                    return (
                        AutoscalerDecision(
                            pool_id=pid,
                            action="NOOP",
                            current_nodes=pool_state.current_nodes,
                            target_nodes=pool_state.current_nodes,
                            pending_jobs=remaining,
                            reason=f"Host capacity unavailable in pool {pid}; trying next fallback pool",
                        ),
                        remaining,
                    )

        dec = await self.reconcile_pool(
            pool_id=pid,
            pending_jobs=max(0, remaining),
            running_jobs=running_jobs,
            tenant_id=tenant_id,
            now=ts,
            pool_state=pool_state,
        )
        contributed = self._pool_capacity_contributed(dec, pool_state)
        return dec, max(0, remaining - contributed)

    async def reconcile_priority_pools(
        self,
        pool_ids: Sequence[str],
        pending_jobs: int,
        running_jobs: int = 0,
        tenant_id: str | None = None,
        now: float | None = None,
    ) -> list[AutoscalerDecision]:
        """Reconcile ordered fallback pools (`A1 -> A4 -> E5`) with capacity probing.

        Args:
            pool_ids: Ordered sequence of pool IDs from highest to lowest preference.
            pending_jobs: Total pending slice backlog.
            running_jobs: Currently executing job/lease count.
            tenant_id: Optional tenant ID for budget ledger evaluation.
            now: Optional epoch timestamp override for deterministic testing.

        Returns:
            List of applied AutoscalerDecision objects in priority order.

        Notes/Architectural Intent:
            Probes host capacity before attempting scale-up on preferred Always-Free/ARM64
            pools so exhausted ADs immediately spill over to fallback x86_64 pools instead
            of stalling CI queues behind a single baseline node. Isolates per-pool errors
            so a transient CSP error on one pool never aborts downstream fallback pools.
        """
        ts = time.time() if now is None else now
        if pending_jobs <= 0:
            return await self._reconcile_priority_scale_down(
                pool_ids=pool_ids,
                running_jobs=running_jobs,
                tenant_id=tenant_id,
                now=ts,
            )

        decisions: list[AutoscalerDecision] = []
        remaining = pending_jobs
        for pid in pool_ids:
            try:
                dec, remaining = await self._reconcile_priority_pool_step(
                    pid=pid,
                    remaining=remaining,
                    running_jobs=running_jobs,
                    tenant_id=tenant_id,
                    ts=ts,
                )
            except Exception as exc:
                dec = AutoscalerDecision(
                    pool_id=pid,
                    action="NOOP",
                    current_nodes=0,
                    target_nodes=0,
                    pending_jobs=remaining,
                    reason=f"Pool evaluation error ({type(exc).__name__}): {exc}; continuing",
                )
            if dec is not None:
                decisions.append(dec)
        return decisions


__all__ = [
    "BudgetAwareInstancePoolAutoscaler",
    "BudgetStrategyMode",
    "CreditPacingPolicy",
]
