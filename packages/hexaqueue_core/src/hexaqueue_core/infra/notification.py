"""Notification dispatching and alerting router for cluster lifecycle events.

Notes/Architectural Intent:
    Orchestrates notification delivery across jobs, runs, and workflow steps
    by matching lifecycle triggers against configured NotificationPolicy instances.
    Integrates Hexastack NotificationPort, handles dynamic target URL registration,
    formats markdown diagnostics, and provides non-blocking async dispatching via
    worker thread offloading to keep scheduler event loops responsive.
"""

from __future__ import annotations

import asyncio
from typing import Any

from hexastack_core.ports.notification import (
    NotificationPort,
    NotificationPriority,
)

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.notification import (
    NotificationPolicy,
    NotificationTrigger,
)
from hexaqueue_core.domain.run import RunSpec


class NotificationDispatcher:
    """Dispatches notifications based on NotificationPolicy rules and lifecycle events.

    Notes/Architectural Intent:
        Decouples lifecycle state machines from physical notification delivery.
        Gracefully handles scenarios where notifications are disabled (port is None).
    """

    def __init__(
        self,
        notification_port: NotificationPort | None = None,
        default_policies: list[NotificationPolicy] | None = None,
    ) -> None:
        """Initialize notification dispatcher.

        Args:
            notification_port: Underlying Hexastack NotificationPort adapter
                (e.g. AppriseNotificationAdapter, StdoutNotificationAdapter).
            default_policies: Global fallback policies applied if entities define none.
        """
        self._port = notification_port
        self._default_policies = list(default_policies or [])

    @property
    def is_enabled(self) -> bool:
        """Check whether notifications are actively configured."""
        return self._port is not None

    def dispatch_job_event(
        self,
        job: JobSpec,
        trigger: NotificationTrigger,
        details: dict[str, Any] | None = None,
    ) -> list[bool]:
        """Synchronously evaluate policies and dispatch alerts for a job lifecycle event.

        Args:
            job: The affected JobSpec.
            trigger: Fired lifecycle trigger.
            details: Optional contextual metadata (exit code, node ID, preemption reason).

        Returns:
            List of boolean results indicating delivery status for each matched policy.
        """
        if not self._port:
            return []

        policies = job.notifications or self._default_policies
        results: list[bool] = []
        context = dict(details or {})

        for policy in policies:
            if not policy.triggers.matches(trigger):
                continue

            # Dynamically register target destinations if supported by adapter
            self._ensure_targets(policy.targets)

            title = f"[Hexaqueue] Job {job.name} ({job.id}): {trigger.name}"
            body = self._format_job_body(job, trigger, context, policy.template)
            priority = self._calculate_priority(policy, trigger)
            tags = list(policy.tags) + [trigger.name.lower(), "job", "hexaqueue"]

            delivered = self._port.notify(
                title=title,
                body=body,
                priority=priority,
                tags=tags,
            )
            results.append(delivered)

        return results

    def dispatch_run_event(
        self,
        run: RunSpec,
        trigger: NotificationTrigger,
        details: dict[str, Any] | None = None,
    ) -> list[bool]:
        """Synchronously evaluate policies and dispatch alerts for an aggregated run event.

        Args:
            run: The affected RunSpec.
            trigger: Fired lifecycle trigger.
            details: Optional contextual metadata (total jobs, duration, failed count).

        Returns:
            List of boolean results indicating delivery status for each matched policy.
        """
        if not self._port:
            return []

        policies = run.notifications or self._default_policies
        results: list[bool] = []
        context = dict(details or {})

        for policy in policies:
            if not policy.triggers.matches(trigger):
                continue

            self._ensure_targets(policy.targets)

            title = f"[Hexaqueue] Run {run.name} ({run.id}): {trigger.name}"
            body = self._format_run_body(run, trigger, context, policy.template)
            priority = self._calculate_priority(policy, trigger)
            tags = list(policy.tags) + [trigger.name.lower(), "run", "hexaqueue"]

            delivered = self._port.notify(
                title=title,
                body=body,
                priority=priority,
                tags=tags,
            )
            results.append(delivered)

        return results

    def dispatch_step_event(
        self,
        workflow_id: str,
        step_name: str,
        trigger: NotificationTrigger,
        policies: list[NotificationPolicy] | None = None,
        details: dict[str, Any] | None = None,
    ) -> list[bool]:
        """Synchronously evaluate policies and dispatch alerts for a workflow step event.

        Args:
            workflow_id: Parent workflow or DAG execution ID.
            step_name: Specific workflow step identifier.
            trigger: Fired lifecycle trigger.
            policies: Explicit step-level notification policies.
            details: Optional contextual metadata.

        Returns:
            List of boolean results indicating delivery status for each matched policy.
        """
        if not self._port:
            return []

        active_policies = policies or self._default_policies
        results: list[bool] = []
        context = dict(details or {})

        for policy in active_policies:
            if not policy.triggers.matches(trigger):
                continue

            self._ensure_targets(policy.targets)

            title = (
                f"[Hexaqueue] Workflow {workflow_id} Step {step_name}: {trigger.name}"
            )
            body = self._format_step_body(
                workflow_id, step_name, trigger, context, policy.template
            )
            priority = self._calculate_priority(policy, trigger)
            tags = list(policy.tags) + [
                trigger.name.lower(),
                "workflow",
                "step",
                "hexaqueue",
            ]

            delivered = self._port.notify(
                title=title,
                body=body,
                priority=priority,
                tags=tags,
            )
            results.append(delivered)

        return results

    async def async_dispatch_job_event(
        self,
        job: JobSpec,
        trigger: NotificationTrigger,
        details: dict[str, Any] | None = None,
    ) -> list[bool]:
        """Asynchronously dispatch job notifications offloaded to a worker thread.

        Args:
            job: The affected JobSpec.
            trigger: Fired lifecycle trigger.
            details: Optional contextual metadata.

        Returns:
            List of boolean delivery results.
        """
        if not self._port:
            return []
        return await asyncio.to_thread(self.dispatch_job_event, job, trigger, details)

    async def async_dispatch_run_event(
        self,
        run: RunSpec,
        trigger: NotificationTrigger,
        details: dict[str, Any] | None = None,
    ) -> list[bool]:
        """Asynchronously dispatch run notifications offloaded to a worker thread.

        Args:
            run: The affected RunSpec.
            trigger: Fired lifecycle trigger.
            details: Optional contextual metadata.

        Returns:
            List of boolean delivery results.
        """
        if not self._port:
            return []
        return await asyncio.to_thread(self.dispatch_run_event, run, trigger, details)

    async def async_dispatch_step_event(
        self,
        workflow_id: str,
        step_name: str,
        trigger: NotificationTrigger,
        policies: list[NotificationPolicy] | None = None,
        details: dict[str, Any] | None = None,
    ) -> list[bool]:
        """Asynchronously dispatch step notifications offloaded to a worker thread.

        Args:
            workflow_id: Parent workflow ID.
            step_name: Workflow step name.
            trigger: Fired lifecycle trigger.
            policies: Step policies.
            details: Contextual metadata.

        Returns:
            List of boolean delivery results.
        """
        if not self._port:
            return []
        return await asyncio.to_thread(
            self.dispatch_step_event, workflow_id, step_name, trigger, policies, details
        )

    def _ensure_targets(self, targets: list[str]) -> None:
        """Register dynamic target URLs with the notification port if supported."""
        if self._port is not None:
            add_fn = getattr(self._port, "add_url", None)
            if callable(add_fn):
                for target in targets:
                    add_fn(target)

    def _calculate_priority(
        self,
        policy: NotificationPolicy,
        trigger: NotificationTrigger,
    ) -> NotificationPriority:
        """Determine effective priority with optional error escalation."""
        if policy.escalate_on_error and trigger in NotificationTrigger.ERRORS:
            if trigger in (NotificationTrigger.FAILED, NotificationTrigger.TIMED_OUT):
                return NotificationPriority.HIGH
            return NotificationPriority.HIGH
        return policy.priority

    def _format_job_body(
        self,
        job: JobSpec,
        trigger: NotificationTrigger,
        context: dict[str, Any],
        template: str | None,
    ) -> str:
        """Format markdown body for a job notification."""
        if template:
            return template.format(job=job, trigger=trigger, **context)

        lines = [
            f"**Job:** `{job.name}` (`{job.id}`)",
            f"**Run ID:** `{job.run_id}`",
            f"**Trigger:** `{trigger.name}`",
            f"**Current State:** `{job.state.value}`",
        ]
        if job.outcome:
            lines.append(f"**Outcome:** `{job.outcome.value}`")
        if "exit_code" in context:
            lines.append(f"**Exit Code:** `{context['exit_code']}`")
        if "node_id" in context:
            lines.append(f"**Node:** `{context['node_id']}`")
        if "reason" in context and context["reason"]:
            lines.append(f"**Reason:** {context['reason']}")
        elif job.status.reason:
            lines.append(f"**Reason:** {job.status.reason}")

        lines.extend(
            [
                f"**Command:** `{job.command}`",
                f"**CPUs / RAM:** {job.resources.cpus} cores / {job.resources.ram_mb} MB",
            ]
        )
        return "\n".join(lines)

    def _format_run_body(
        self,
        run: RunSpec,
        trigger: NotificationTrigger,
        context: dict[str, Any],
        template: str | None,
    ) -> str:
        """Format markdown body for an aggregated run notification."""
        if template:
            return template.format(run=run, trigger=trigger, **context)

        lines = [
            f"**Run:** `{run.name}` (`{run.id}`)",
            f"**Trigger:** `{trigger.name}`",
            f"**Current State:** `{run.state.value}`",
        ]
        if run.outcome:
            lines.append(f"**Outcome:** `{run.outcome.value}`")
        lines.append(f"**Total Jobs:** {len(run.jobs)}")

        if "completed_jobs" in context:
            lines.append(f"**Completed Jobs:** {context['completed_jobs']}")
        if "failed_jobs" in context:
            lines.append(f"**Failed Jobs:** {context['failed_jobs']}")
        if "duration_seconds" in context:
            lines.append(f"**Duration:** {context['duration_seconds']:.2f}s")

        return "\n".join(lines)

    def _format_step_body(
        self,
        workflow_id: str,
        step_name: str,
        trigger: NotificationTrigger,
        context: dict[str, Any],
        template: str | None,
    ) -> str:
        """Format markdown body for a workflow step notification."""
        if template:
            return template.format(
                workflow_id=workflow_id,
                step_name=step_name,
                trigger=trigger,
                **context,
            )

        lines = [
            f"**Workflow:** `{workflow_id}`",
            f"**Step:** `{step_name}`",
            f"**Trigger:** `{trigger.name}`",
        ]
        if "error" in context:
            lines.append(f"**Error:** {context['error']}")
        if "duration_seconds" in context:
            lines.append(f"**Duration:** {context['duration_seconds']:.2f}s")

        return "\n".join(lines)


__all__ = [
    "NotificationDispatcher",
]
