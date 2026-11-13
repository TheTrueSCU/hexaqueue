"""Kubernetes coordination.v1.Lease leader election adapter.

Notes/Architectural Intent:
    Implements LeaderElectionPort using standard Kubernetes `coordination.v1.Lease`
    API objects (or an injected hermetic client / HTTP transport) for zero-external-dependency
    high-availability controller failover inside Kubernetes and Kueue clusters.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from hexaqueue_core.domain.coordination import CrossLoopAsyncLock, LeaderLease
from hexaqueue_core.ports.coordination import LeaderElectionPort


class KubernetesLeaseClientProtocol(Protocol):
    """Protocol for Kubernetes coordination.v1 Lease operations."""

    def read_namespaced_lease(self, name: str, namespace: str) -> dict[str, Any] | None:
        """Read a Lease resource by name and namespace."""

    def create_namespaced_lease(
        self, namespace: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a new Lease resource in the namespace."""

    def replace_namespaced_lease(
        self, name: str, namespace: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Replace an existing Lease resource in the namespace."""

    def delete_namespaced_lease(self, name: str, namespace: str) -> None:
        """Delete a Lease resource in the namespace."""


class _InMemoryK8sLeaseStore:
    """Hermetic in-memory store emulating Kubernetes coordination.v1.Lease API."""

    def __init__(self) -> None:
        self._leases: dict[tuple[str, str], dict[str, Any]] = {}

    def read_namespaced_lease(self, name: str, namespace: str) -> dict[str, Any] | None:
        return self._leases.get((namespace, name))

    def create_namespaced_lease(
        self, namespace: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        name = body["metadata"]["name"]
        self._leases[(namespace, name)] = dict(body)
        return self._leases[(namespace, name)]

    def replace_namespaced_lease(
        self, name: str, namespace: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        self._leases[(namespace, name)] = dict(body)
        return self._leases[(namespace, name)]

    def delete_namespaced_lease(self, name: str, namespace: str) -> None:
        self._leases.pop((namespace, name), None)


class KubernetesLeaseLeaderAdapter(LeaderElectionPort):
    """Leader election adapter backed by Kubernetes `coordination.v1.Lease` objects.

    Args:
        lease_name: Name of the Kubernetes Lease object.
        namespace: Kubernetes namespace hosting the Lease.
        client: Optional Kubernetes Lease API client (defaults to hermetic store).

    Notes/Architectural Intent:
        Stores `holderIdentity`, `leaseDurationSeconds`, `acquireTime`, `renewTime`,
        and `leaseTransitions` in standard Kubernetes `coordination.v1.LeaseSpec`
        format while enforcing UTC TTL fencing.
    """

    def __init__(
        self,
        lease_name: str = "hexaqueue-controller-leader",
        namespace: str = "default",
        client: KubernetesLeaseClientProtocol | None = None,
    ) -> None:
        """Initialize Kubernetes Lease leader election adapter."""
        self._lease_name = lease_name
        self._namespace = namespace
        self._client: KubernetesLeaseClientProtocol = client or _InMemoryK8sLeaseStore()
        self._lock = CrossLoopAsyncLock()

    @staticmethod
    def _parse_lease_doc(doc: dict[str, Any] | None) -> LeaderLease | None:
        """Convert a Kubernetes Lease dictionary into a domain LeaderLease."""
        if not doc:
            return None
        spec = doc.get("spec") or {}
        holder = spec.get("holderIdentity")
        if not holder:
            return None
        duration = float(spec.get("leaseDurationSeconds", 15.0))
        acquire_raw = spec.get("acquireTime")
        renew_raw = spec.get("renewTime") or acquire_raw
        transitions = int(spec.get("leaseTransitions", 0))

        acquired_at = (
            datetime.fromisoformat(acquire_raw)
            if isinstance(acquire_raw, str)
            else datetime.now(UTC)
        )
        renewed_at = (
            datetime.fromisoformat(renew_raw)
            if isinstance(renew_raw, str)
            else acquired_at
        )
        expires_at = renewed_at + timedelta(seconds=duration)
        return LeaderLease(
            acquired_at=acquired_at,
            expires_at=expires_at,
            leader_id=str(holder),
            lease_duration_seconds=duration,
            renewal_count=transitions,
        )

    def _build_lease_doc(
        self,
        leader_id: str,
        duration_seconds: float,
        acquired_at: datetime,
        renewed_at: datetime,
        renewal_count: int,
    ) -> dict[str, Any]:
        """Construct a Kubernetes coordination.v1.Lease payload."""
        return {
            "apiVersion": "coordination.k8s.io/v1",
            "kind": "Lease",
            "metadata": {
                "name": self._lease_name,
                "namespace": self._namespace,
            },
            "spec": {
                "holderIdentity": leader_id,
                "leaseDurationSeconds": duration_seconds,
                "acquireTime": acquired_at.isoformat(),
                "renewTime": renewed_at.isoformat(),
                "leaseTransitions": renewal_count,
            },
        }

    async def acquire_leadership(
        self,
        candidate_id: str,
        lease_duration_seconds: float = 15.0,
    ) -> bool:
        """Attempt to acquire active leadership via Kubernetes Lease."""
        deposed_leader: str | None = None
        newly_elected = False

        async with self._lock:
            now = datetime.now(UTC)
            doc = await asyncio.to_thread(
                self._client.read_namespaced_lease,
                self._lease_name,
                self._namespace,
            )
            current = self._parse_lease_doc(doc)

            if current is not None:
                if not current.is_expired(now):
                    if current.leader_id == candidate_id:
                        updated_doc = self._build_lease_doc(
                            leader_id=candidate_id,
                            duration_seconds=lease_duration_seconds,
                            acquired_at=current.acquired_at,
                            renewed_at=now,
                            renewal_count=current.renewal_count + 1,
                        )
                        await asyncio.to_thread(
                            self._client.replace_namespaced_lease,
                            self._lease_name,
                            self._namespace,
                            updated_doc,
                        )
                        return True
                    return False

                if current.leader_id != candidate_id:
                    deposed_leader = current.leader_id

                replacement_doc = self._build_lease_doc(
                    leader_id=candidate_id,
                    duration_seconds=lease_duration_seconds,
                    acquired_at=now,
                    renewed_at=now,
                    renewal_count=0,
                )
                await asyncio.to_thread(
                    self._client.replace_namespaced_lease,
                    self._lease_name,
                    self._namespace,
                    replacement_doc,
                )
                newly_elected = True
            else:
                new_doc = self._build_lease_doc(
                    leader_id=candidate_id,
                    duration_seconds=lease_duration_seconds,
                    acquired_at=now,
                    renewed_at=now,
                    renewal_count=0,
                )
                await asyncio.to_thread(
                    self._client.create_namespaced_lease,
                    self._namespace,
                    new_doc,
                )
                newly_elected = True

        if deposed_leader is not None:
            await self._notify_deposed(deposed_leader)
        if newly_elected:
            await self._notify_elected(candidate_id)
        return True

    async def renew_leadership(
        self,
        candidate_id: str,
        lease_duration_seconds: float = 15.0,
    ) -> bool:
        """Renew Kubernetes Lease if currently held by candidate."""
        deposed_leader: str | None = None
        async with self._lock:
            now = datetime.now(UTC)
            doc = await asyncio.to_thread(
                self._client.read_namespaced_lease,
                self._lease_name,
                self._namespace,
            )
            current = self._parse_lease_doc(doc)
            if current is None:
                return False
            if current.is_expired(now):
                if current.leader_id == candidate_id:
                    deposed_leader = candidate_id
                await asyncio.to_thread(
                    self._client.delete_namespaced_lease,
                    self._lease_name,
                    self._namespace,
                )
                if deposed_leader is not None:
                    await self._notify_deposed(deposed_leader)
                return False
            if current.leader_id != candidate_id:
                return False

            updated_doc = self._build_lease_doc(
                leader_id=candidate_id,
                duration_seconds=lease_duration_seconds,
                acquired_at=current.acquired_at,
                renewed_at=now,
                renewal_count=current.renewal_count + 1,
            )
            await asyncio.to_thread(
                self._client.replace_namespaced_lease,
                self._lease_name,
                self._namespace,
                updated_doc,
            )
            return True

    async def release_leadership(self, candidate_id: str) -> None:
        """Release active leadership held by candidate."""
        released = False
        async with self._lock:
            doc = await asyncio.to_thread(
                self._client.read_namespaced_lease,
                self._lease_name,
                self._namespace,
            )
            current = self._parse_lease_doc(doc)
            if current is not None and current.leader_id == candidate_id:
                await asyncio.to_thread(
                    self._client.delete_namespaced_lease,
                    self._lease_name,
                    self._namespace,
                )
                released = True

        if released:
            await self._notify_deposed(candidate_id)

    async def get_current_leader(self) -> LeaderLease | None:
        """Retrieve active Kubernetes Lease if unexpired."""
        expired_leader: str | None = None
        async with self._lock:
            now = datetime.now(UTC)
            doc = await asyncio.to_thread(
                self._client.read_namespaced_lease,
                self._lease_name,
                self._namespace,
            )
            current = self._parse_lease_doc(doc)
            if current is not None and current.is_expired(now):
                expired_leader = current.leader_id
                await asyncio.to_thread(
                    self._client.delete_namespaced_lease,
                    self._lease_name,
                    self._namespace,
                )
                current = None

        if expired_leader is not None:
            await self._notify_deposed(expired_leader)
        return current

    async def is_leader(self, candidate_id: str) -> bool:
        """Check whether candidate holds active Kubernetes Lease."""
        active = await self.get_current_leader()
        return active is not None and active.leader_id == candidate_id


__all__ = [
    "KubernetesLeaseClientProtocol",
    "KubernetesLeaseLeaderAdapter",
]
