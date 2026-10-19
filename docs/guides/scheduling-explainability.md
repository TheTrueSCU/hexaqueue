# Scheduling Decision Explainability & Fair-Share Math Guide

> Deep transparency and mathematical explainability into Hexaqueue's hierarchical fair-share scheduler.

---

## 1. Why Is My Job Pending? (`hq why`)

When submitting large workloads to a shared HPC compute cluster, jobs may wait in the queue. Instead of opaque status flags, Hexaqueue provides the `hq why` command to deliver instant, human-readable diagnoses of dispatch bottlenecks:

```bash
hq why transformer-layer-shard
```

Example Output:
```
Why Pending: Job 'transformer-layer-shard' is waiting for 4 available GPUs on worker node pool 'gpu-a100'.
```

---

## 2. Multi-Factor Scheduling Decision Breakdown (`hq explain`)

To inspect the mathematical formula and factor weights used by the priority engine, run `hq explain`:

```bash
hq explain transformer-layer-shard
```

The report breaks down:
- **Fair-Share Factor ($f_{\text{fs}}$)**: Based on hierarchical organization usage decay.
- **Job Age Factor ($f_{\text{age}}$)**: Linear scaling preventing starvation of long-waiting jobs.
- **Partition Weight ($f_{\text{partition}}$)**: Administrative priority assigned to the target queue.
- **Resource Blockers**: Exact list of worker constraints preventing immediate dispatch.

---

## 3. Hierarchical Fair-Share Tree (`hq fairshare` & `hq quota`)

Inspect the hierarchical organization tree, decay half-life, and accumulated compute units across teams:

```bash
hq fairshare
hq quota
```

All allocations decay exponentially according to the configured cluster half-life ($t_{1/2}$), ensuring teams that have been dormant automatically regain maximum scheduling priority upon submitting new workloads.
