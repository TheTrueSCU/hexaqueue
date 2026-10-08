# Security Policy

## Supported Versions

Only the **latest minor release** of each Hexaqueue package receives security fixes.
Older minor versions are not backported.

| Package | Supported |
|---|---|
| `hexaqueue` (latest minor) | ✅ |
| `hexaqueue_core` (latest minor) | ✅ |
| `hexaqueue_worker` (latest minor) | ✅ |
| `hexaqueue_server` (latest minor) | ✅ |
| `hexaqueue_cli` (latest minor) | ✅ |
| `hexaqueue_dashboard` (latest minor) | ✅ |
| `hexaqueue_workflow` (latest minor) | ✅ |
| `hexaqueue_collateral` (latest minor) | ✅ |
| `hexaqueue_scanner` (latest minor) | ✅ |
| Any older minor of the above | ❌ |

## Reporting a Vulnerability

> [!CAUTION]
> **Do not open a public GitHub issue for security vulnerabilities.** Public disclosure before a fix is available puts all users at risk.

Please report vulnerabilities using **GitHub's private vulnerability reporting**:

👉 [Open a private security advisory](https://github.com/TheTrueSCU/hexaqueue/security/advisories/new)

Your report will be visible only to repository maintainers until a coordinated disclosure is agreed upon. Provide as much detail as possible:

- Affected package(s) and version(s)
- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept (PoC)
- Any suggested mitigations you have identified

## Scope

### In scope

- All packages listed in the [Supported Versions](#supported-versions) table at their latest minor release
- Third-party dependencies **directly introduced into a user's environment by Hexaqueue** (i.e. listed in Hexaqueue's own `dependencies` in `pyproject.toml`)
- Collateral isolation, quarantine scanners, and container/cgroup enforcement mechanisms

### Out of scope

- Application code executed within user workloads
- Third-party libraries not in Hexaqueue's direct dependency graph
- Issues in dependencies that Hexaqueue does not pin, vendor, or introduce directly
- Social engineering attacks targeting contributors or maintainers
- Denial-of-service issues requiring physical access to the host
- Reports against unsupported older minor versions

## Response Timeline & SLA

| Milestone | Target |
|---|---|
| Initial Acknowledgement of report | Within **48 hours** |
| Triage and severity assessment | Within **7 business days** of acknowledgement |
| Coordinated fix & CVE assignment | Agreed with reporter; typically within **30 to 60 days** for critical issues |

We will keep you informed of progress at each milestone. If you believe a critical issue warrants an accelerated timeline, please state so in your report.

## Credit & Vulnerability Acknowledgment

We believe in giving credit where credit is due. Unless you request to remain anonymous, we will publicly credit you in our:
1. Release notes and `CHANGELOG.md`
2. GitHub Security Advisory release page
3. CVE metadata / attribution records

## Safe Harbour

Hexaqueue maintainers commit to working in **good faith** with security researchers who:

- Report vulnerabilities privately before any public disclosure
- Avoid accessing, modifying, or destroying data that does not belong to them
- Do not degrade the availability of Hexaqueue services or infrastructure
- Do not violate the privacy of other users

Researchers who follow these principles will not be subject to legal action related to their research. We will work with you to understand and resolve the issue promptly.

## Security Assurance Case

Hexaqueue maintains a formal security assurance case to demonstrate why its security requirements and architectural guarantees are met.

### 1. Threat Model & Asset Identification
* **Primary Assets**: Integrity and isolation of job queue scheduling, worker cgroup and resource bounds, collateral staging isolation and quarantine integrity, administrative role-based access control (RBAC), and bastioned PTY session access.
* **Threat Vectors**:
  * *Privilege Escalation*: Unauthorized execution elevation or administrative token forgery across server endpoints and CLI bridges.
  * *Path Traversal & Host Infiltration*: Malicious collateral ingestion paths escaping staging directories.
  * *Resource Starvation & Escape*: Job processes exceeding cgroup CPU/memory bounds or leaving orphaned GPU scratch state.
  * *Supply Chain & Dependency Injection*: Vulnerabilities introduced via third-party PyPI dependencies.

### 2. Trust Boundaries
* **External Transport Boundary**: Inbound API requests, CLI invocations, and Web dashboard actions cross an explicit authentication context boundary. Admin elevation requires explicit server token validation.
* **Collateral Ingestion Boundary**: Uploaded collateral is strictly validated against path traversal (`..`, absolute paths) and processed through a fail-closed multi-engine quarantine scanner before being admitted to execution staging.
* **Worker Isolation Boundary**: Job tasks execute within strictly managed cgroups with sandboxed PTY bridges and isolated working directories. Cleanups execute inside guaranteed `finally` routines to prevent resource leakage.

### 3. Secure Design Principles Applied
* **Strict Least Privilege**: Unauthenticated or default user sessions cannot cancel or mutate runs owned by other users without administrative escalation.
* **Fail-Closed Scanner Defaults**: Quarantine scanning fails closed (`QUARANTINED`) if scanning engines are unconfigured or fail to initialize.
* **Separation of Concerns**: Hexagonal layering isolates domain scheduling logic from transport and storage adapters.

### 4. Implementation Security Weakness Countermeasures
* **Automated Static Analysis (SAST)**: Enforced via `Ruff` (security rules `S`), `ty check`, and GitHub `CodeQL`.
* **Automated Dependency Auditing (SCA)**: Continuous `Dependabot` vulnerability monitoring and pre-commit `pip-audit` scans.
* **Secret Detection**: `detect-secrets` hook in pre-commit prevents accidental credential check-ins.

---

## Preferred Disclosure Language

Please submit all reports in **English** to ensure the fastest possible triage and response.

---

*This policy follows coordinated disclosure best practices and OpenSSF Gold standards. Last reviewed: 2026-10.*
