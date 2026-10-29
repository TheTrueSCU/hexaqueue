"""Budget and queue-depth driven instance pool autoscaler.

Notes/Architectural Intent:
    Orchestrates dynamic capacity scaling across cloud instance pools.
    Evaluates pending job queue depth by capability tag, enforces budget
    limits via BudgetAccountingPort, and scales idle pools down to zero.
"""

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
    ) -> None:
        """Initialize autoscaler engine.

        Args:
            governors: Mapping of pool_id to its corresponding InstancePoolGovernorPort.
            budget_port: Optional BudgetAccountingPort for credit balance checks.
            min_budget_reserve: Minimum available credits required before scale-out.
        """
        self._governors = governors or {}
        self._budget_port = budget_port
        self._min_budget_reserve = min_budget_reserve

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
    ) -> AutoscalerDecision:
        """Evaluate and apply scaling decision to the target pool governor.

        Args:
            pool_id: Unique pool identifier.
            pending_jobs: Number of queued jobs matching pool capability tags.
            running_jobs: Number of currently executing jobs in this pool.
            tenant_id: Optional tenant identifier for budget accounting checks.

        Returns:
            Applied AutoscalerDecision.

        Raises:
            HexaqueueError: If no governor is registered for the specified pool_id.
        """
        governor = self._governors.get(pool_id)
        if governor is None:
            msg = f"No governor registered for pool '{pool_id}'"
            raise HexaqueueError(msg)

        pool_state = await governor.get_pool_state(pool_id)

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
            await governor.scale_pool(
                PoolScaleRequest(
                    pool_id=pool_id,
                    target_nodes=decision.target_nodes,
                    reason=decision.reason,
                )
            )

        return decision
