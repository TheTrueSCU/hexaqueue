# Feature Demos & Walkthroughs

> Visual, narrated walkthroughs recorded automatically via our test suites using `RECORD_DEMO=1`.

---

## 1. HPC Workload Batch Submission & Streaming Logs (`HXQ-01`)

Watch `hq` submit a declarative multi-step workload DAG with task dependencies, stream execution status, and demux live logs directly from compute worker processes.

<video controls autoplay loop muted playsinline width="100%" style="border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,0.4);">
  <source src="assets/demos/hexaqueue-workload-submission.webm" type="video/webm">
  <track label="English" kind="subtitles" srclang="en" src="assets/demos/hexaqueue-workload-submission.vtt" default>
</video>

---

## 2. Interactive Cluster Top & Hierarchical Job Explainability (`HXQ-02`)

Inspect live cluster telemetry, query worker nodes and fair-share quota trees, diagnose dispatch blockers with `hq why`, and break down multi-factor scheduling decisions with `hq explain`.

<video controls autoplay loop muted playsinline width="100%" style="border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,0.4);">
  <source src="assets/demos/hexaqueue-cluster-top-why.webm" type="video/webm">
  <track label="English" kind="subtitles" srclang="en" src="assets/demos/hexaqueue-cluster-top-why.vtt" default>
</video>

---

## 3. Tiered Collateral Content-Addressable Storage (`HXQ-03`)

Stage large model weights and datasets into Content-Addressable Storage (CAS), verifying cryptographic SHA-256 deduplication and local worker NVMe caching without redundant WAN transfers.

<video controls autoplay loop muted playsinline width="100%" style="border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,0.4);">
  <source src="assets/demos/hexaqueue-tiered-collateral-cas.webm" type="video/webm">
  <track label="English" kind="subtitles" srclang="en" src="assets/demos/hexaqueue-tiered-collateral-cas.vtt" default>
</video>
