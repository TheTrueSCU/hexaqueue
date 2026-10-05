"""Multi-tenant privacy and redaction filter for scheduler explainability.

Notes/Architectural Intent:
    Guarantees cross-tenant data isolation and privacy protection (PII/CUI).
    Ensures non-admin users querying queue rankings or explaining jobs cannot observe
    proprietary command lines, environment variables, or other tenants' identities.
"""

import hashlib
import re

from hexaqueue_core.domain.explainability import (
    FairShareNodeReport,
    FairShareTreeReport,
    PendingReason,
    PriorityBreakdown,
    SchedulingDecisionReport,
)


class MultiTenantRedactionFilter:
    """Filter enforcing multi-tenant isolation on scheduler explainability reports.

    Notes/Architectural Intent:
        Applies deterministic pseudonymization to other tenants' job and user IDs,
        while preserving cluster contention metrics (rank, total jobs, slots) so
        users understand queue dynamics without leaking cross-tenant data.
    """

    def __init__(self, salt: str = "hexaqueue-redaction-salt") -> None:
        """Initialize redaction filter with a pseudonymization salt.

        Args:
            salt: Salt string used for stable one-way pseudonym hashing.
        """
        self._salt = salt

    def redact_decision_report(
        self,
        report: SchedulingDecisionReport,
        requesting_user: str,
        is_admin: bool = False,
    ) -> SchedulingDecisionReport:
        """Sanitize a scheduling decision report based on tenant authorization.

        Args:
            report: Source SchedulingDecisionReport.
            requesting_user: Identifier of user initiating the inquiry.
            is_admin: Whether the requesting user holds cluster admin privileges.

        Returns:
            Sanitized SchedulingDecisionReport (redacted if cross-tenant).
        """
        if is_admin or requesting_user == report.user:
            return report.model_copy(deep=True)

        # Cross-tenant view: pseudonymize target user and blocking anchors
        pseudo_user = self.pseudonymize_user(report.user)
        pseudo_anchor = (
            self.pseudonymize_job(report.blocking_anchor_id)
            if report.blocking_anchor_id
            else None
        )

        redacted_reasons: list[PendingReason] = []
        for reason in report.pending_reasons:
            sanitized_msg = self._sanitize_text(
                reason.message,
                sensitive_terms=[report.user, report.blocking_anchor_id or ""],
            )
            sanitized_details = {
                k: v
                for k, v in reason.details.items()
                if k not in ("anchor_id", "anchor_user", "actual_usage")
            }
            if pseudo_anchor:
                sanitized_details["anchor_id"] = pseudo_anchor
            redacted_reasons.append(
                PendingReason(
                    code=reason.code,
                    message=sanitized_msg,
                    details=sanitized_details,
                )
            )

        sanitized_summary = self._sanitize_text(
            report.summary,
            sensitive_terms=[report.user, report.blocking_anchor_id or ""],
        )

        # Zero-out other tenant's raw usage in priority breakdown
        sanitized_breakdown = PriorityBreakdown(
            base_score=report.priority_breakdown.base_score,
            age_score=report.priority_breakdown.age_score,
            fairshare_score=report.priority_breakdown.fairshare_score,
            preemption_bonus=report.priority_breakdown.preemption_bonus,
            total_priority=report.priority_breakdown.total_priority,
            age_seconds=report.priority_breakdown.age_seconds,
            fairshare_factor=report.priority_breakdown.fairshare_factor,
            target_share=report.priority_breakdown.target_share,
            actual_usage=0.0,  # Redacted
        )

        return SchedulingDecisionReport(
            job_id=report.job_id,
            user=pseudo_user,
            state=report.state,
            queue_position=report.queue_position,
            queue_total=report.queue_total,
            priority_breakdown=sanitized_breakdown,
            pending_reasons=redacted_reasons,
            blocking_anchor_id=pseudo_anchor,
            required_slots=report.required_slots,
            available_slots=report.available_slots,
            total_slots=report.total_slots,
            estimated_wait_seconds=report.estimated_wait_seconds,
            summary=sanitized_summary,
            is_redacted=True,
        )

    def redact_fairshare_tree(
        self,
        report: FairShareTreeReport,
        requesting_user: str,
        is_admin: bool = False,
    ) -> FairShareTreeReport:
        """Sanitize a fairshare tree report to protect peer usage numbers.

        Args:
            report: Hierarchical fair-share report.
            requesting_user: Inquiring user identifier.
            is_admin: Whether the inquirer has admin visibility.

        Returns:
            Sanitized FairShareTreeReport.
        """
        if is_admin:
            return report.model_copy(deep=True)

        def _sanitize_node(node: FairShareNodeReport) -> FairShareNodeReport:
            is_self = node.id == requesting_user
            is_root = node.id == "root" or node.parent_id is None
            node_id = (
                node.id if (is_self or is_root) else self.pseudonymize_user(node.id)
            )
            raw = node.raw_usage if (is_self or is_root) else 0.0
            decayed = node.decayed_usage if (is_self or is_root) else 0.0

            sanitized_children = [_sanitize_node(c) for c in node.children]
            return FairShareNodeReport(
                id=node_id,
                parent_id=node.parent_id,
                shares=node.shares,
                target_share=node.target_share,
                raw_usage=raw,
                decayed_usage=decayed,
                fairshare_factor=node.fairshare_factor,
                children=sanitized_children,
            )

        sanitized_root = _sanitize_node(report.root)
        return FairShareTreeReport(
            root=sanitized_root,
            half_life_seconds=report.half_life_seconds,
            total_decayed_usage=report.total_decayed_usage,
        )

    def pseudonymize_user(self, user_id: str) -> str:
        """Generate a stable pseudonym for an external tenant user."""
        if not user_id:
            return "user_anon"
        digest = hashlib.sha256(f"{self._salt}:{user_id}".encode()).hexdigest()[:6]
        return f"tenant_user_{digest}"

    def pseudonymize_job(self, job_id: str) -> str:
        """Generate a stable pseudonym for an external tenant job."""
        if not job_id:
            return "job_anon"
        digest = hashlib.sha256(f"{self._salt}:{job_id}".encode()).hexdigest()[:6]
        return f"job_{digest}"

    def _sanitize_text(self, text: str, sensitive_terms: list[str]) -> str:
        """Redact occurrences of sensitive terms from message text."""
        result = text
        for term in sensitive_terms:
            if term:
                pattern = re.compile(re.escape(term), re.IGNORECASE)
                result = pattern.sub(
                    f"***{term[-3:]}" if len(term) > 3 else "***", result
                )
        return result


__all__ = [
    "MultiTenantRedactionFilter",
]
