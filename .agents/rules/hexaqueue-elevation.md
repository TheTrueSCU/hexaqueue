---
trigger: always_on
description: Positive administrative elevation and least privilege invariants for hexaqueue CLI, API, and worker operations.
---

## Hexaqueue Positive Administrative Elevation & Least Privilege

Hexaqueue strictly enforces the principle of least privilege and positive administrative elevation across all operational surfaces (CLI, HTTP API, worker pools, and scheduling engines).

### Core Invariants

1. **Default Least Privilege**:
   - All client and CLI commands run in standard unprivileged user mode by default.
   - Destructive, state-mutating, worker-management, queue-purging, or cluster-reconfiguring operations must never be permitted without explicit elevation.

2. **Explicit Administrative Flag (`--admin`)**:
   - Destructive operations (e.g. `hq cancel --all`, `hq purge`, `hq workers drain`, `hq worker kill`, queue administrative pauses) require explicit `--admin` assertion.
   - CLI commands requesting privileged actions without `--admin` must immediately fail with an actionable authorization error directing the user to explicitly elevate.

3. **Multi-Tenant Domain Boundary Separation**:
   - Standard user scopes may only inspect, submit, query status, or cancel jobs within their authenticated tenant or assigned username scope.
   - Cross-tenant inspection, job re-prioritization, or resource quota overrides strictly require administrative elevation (`role: admin`).

4. **Audit Logging & Telemetry**:
   - Every administrative elevation invocation must be captured in structured audit logs (`audit.elevation`), recording requesting actor, timestamp, target resource, and explicit reason/context.
