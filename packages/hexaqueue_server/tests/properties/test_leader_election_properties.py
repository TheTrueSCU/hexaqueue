"""Dual-implementation oracle property tests for HA leader election adapters.

Notes/Architectural Intent:
    Cross-evaluates DatabaseLeaderElectionAdapter and KubernetesLeaseLeaderAdapter
    against InMemoryLeaderElectionAdapter (reference oracle) across interleaved
    acquire, renew, release, and inspection operations (ADR-002).
"""

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from hexaqueue_core.adapters.coordination.in_memory import (
    InMemoryLeaderElectionAdapter,
)
from hexaqueue_core.adapters.coordination.kubernetes import (
    KubernetesLeaseLeaderAdapter,
)
from hexaqueue_server.adapters.storage.leader import DatabaseLeaderElectionAdapter

_CANDIDATE_STRATEGY = st.sampled_from(["ctrl-a", "ctrl-b", "ctrl-c"])
_ACTION_STRATEGY = st.tuples(
    st.sampled_from(["acquire", "renew", "release", "check"]),
    _CANDIDATE_STRATEGY,
)


@settings(max_examples=25, deadline=None)
@given(actions=st.lists(_ACTION_STRATEGY, min_size=1, max_size=25))
def test_leader_election_dual_oracle_equivalence(
    actions: list[tuple[str, str]],
) -> None:
    """Verify Database and Kubernetes leader adapters match the in-memory reference oracle."""

    async def _run_sequence() -> None:
        oracle = InMemoryLeaderElectionAdapter()
        db_prod = DatabaseLeaderElectionAdapter()
        k8s_prod = KubernetesLeaseLeaderAdapter()

        oracle_elected: list[str] = []
        db_elected: list[str] = []
        k8s_elected: list[str] = []

        oracle_deposed: list[str] = []
        db_deposed: list[str] = []
        k8s_deposed: list[str] = []

        oracle.on_elected(oracle_elected.append)
        db_prod.on_elected(db_elected.append)
        k8s_prod.on_elected(k8s_elected.append)

        oracle.on_deposed(oracle_deposed.append)
        db_prod.on_deposed(db_deposed.append)
        k8s_prod.on_deposed(k8s_deposed.append)

        for op, cid in actions:
            if op == "acquire":
                r_ora = await oracle.acquire_leadership(cid, 60.0)
                r_db = await db_prod.acquire_leadership(cid, 60.0)
                r_k8s = await k8s_prod.acquire_leadership(cid, 60.0)
                assert r_db == r_ora
                assert r_k8s == r_ora
            elif op == "renew":
                r_ora = await oracle.renew_leadership(cid, 60.0)
                r_db = await db_prod.renew_leadership(cid, 60.0)
                r_k8s = await k8s_prod.renew_leadership(cid, 60.0)
                assert r_db == r_ora
                assert r_k8s == r_ora
            elif op == "release":
                await oracle.release_leadership(cid)
                await db_prod.release_leadership(cid)
                await k8s_prod.release_leadership(cid)
            else:
                r_ora = await oracle.is_leader(cid)
                r_db = await db_prod.is_leader(cid)
                r_k8s = await k8s_prod.is_leader(cid)
                assert r_db == r_ora
                assert r_k8s == r_ora

            cur_ora = await oracle.get_current_leader()
            cur_db = await db_prod.get_current_leader()
            cur_k8s = await k8s_prod.get_current_leader()

            ora_id = cur_ora.leader_id if cur_ora else None
            db_id = cur_db.leader_id if cur_db else None
            k8s_id = cur_k8s.leader_id if cur_k8s else None
            assert db_id == ora_id
            assert k8s_id == ora_id

        assert db_elected == oracle_elected
        assert k8s_elected == oracle_elected
        assert db_deposed == oracle_deposed
        assert k8s_deposed == oracle_deposed
        db_prod.close()

    asyncio.run(_run_sequence())
