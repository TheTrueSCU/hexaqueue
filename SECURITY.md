# Security Policy

## Supported Versions

Only the **latest minor release** of each Hexaqueue package receives security fixes.
Older minor versions are not backported.

| Package | Supported |
|---|---|
| `hexaqueue` (latest minor) | ✅ |
| `hexaqueue-core` (latest minor) | ✅ |
| `hexaqueue-cli` (latest minor) | ✅ |
| `hexaqueue-server` (latest minor) | ✅ |
| `hexaqueue-worker` (latest minor) | ✅ |
| `hexaqueue-collateral` (latest minor) | ✅ |
| `hexaqueue-scanner` (latest minor) | ✅ |
| `hexaqueue-monitor` (latest minor) | ✅ |
| `hexaqueue-dashboard` (latest minor) | ✅ |
| `hexaqueue-github-runner` (latest minor) | ✅ |
| `hexaqueue-gitlab-runner` (latest minor) | ✅ |
| `hexaqueue-kueue` (latest minor) | ✅ |
| `hexaqueue-workflow` (latest minor) | ✅ |
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
- Code and execution runtimes managed by `hexaqueue-worker` and `hexaqueue-collateral`

### Out of scope

- User compute payloads and scripts executed within jobs (users are responsible for securing their own workload scripts)
- Third-party cloud providers (AWS Batch, GCP Batch, Kubernetes)
- Social engineering attacks targeting contributors or maintainers
- Denial-of-service issues requiring physical or direct workstation access to the host
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
* **Primary Assets**: Integrity of batch scheduling state and DAG execution graphs, content-addressable storage (CAS) integrity, worker node compute isolation, and quarantine verification before artifact promotion.
* **Threat Vectors**:
  * *Arbitrary Code Execution & Container Escape*: Malicious batch jobs attempting to break out of worker execution environments or tamper with host processes.
  * *Collateral Tampering & Poisoning*: Malicious artifacts or poisoned inputs attempting to bypass checksum verification or quarantine gates.
  * *Denial of Service / Resource Exhaustion*: Compute jobs consuming unlimited RAM/CPU to crash shared worker daemons.
  * *Credential & Secret Leakage*: Sensitive environment variables or secrets leaked into job log streams or telemetry.

### 2. Trust Boundaries
* **External Ingress & CLI Boundary**: All batch pipeline YAML/JSON specifications crossing the submission boundary are strictly validated using Pydantic domain models (`hexaqueue_core`) prior to acceptance by the scheduler controller.
* **Worker Execution Boundary**: Worker jobs run in isolated process groups, rootless OCI containers (Podman/Apptainer), or cgroups v2 slices. Scratch directories (`~/.hexaqueue/scratch/<job_id>`) are hermetically isolated per job and securely deleted on completion.
* **Collateral & Quarantine Boundary**: Direct uploads are staged in quarantined CAS directories (`hexaqueue_collateral`) and cannot be accessed by worker tasks until verified by `hexaqueue_scanner` (checksum validation, ClamAV, and YARA inspection).

### 3. Secure Design Principles Applied
* **Strict Least Privilege**: Compute workers run rootless with unprivileged UID/GIDs and drop unnecessary Linux capabilities.
* **Hermetic Architectural Isolation**: Domain logic (`hexaqueue_core`) has zero framework dependencies, strictly enforced by `import-linter`.
* **Zero-Cost Guard & Free-Tier Clamping**: `FREE_TIER` safety mode ensures zero accidental cloud spend ($0 cloud spend invariant).
* **Fail-Secure Defaults**: Any task failing quarantine, hash verification, or resource bounds is immediately aborted and marked `FAILED` or `QUARANTINED`.

### 4. Implementation Security Weakness Countermeasures
* **Automated Static Analysis (SAST)**: Enforced via `Ruff` (security rules `S`), `ty check`, and GitHub `CodeQL`.
* **Automated Dependency Auditing (SCA)**: Daily `Dependabot` vulnerability monitoring and pre-commit `detect-secrets` checks.
* **Property & Fuzz Testing**: DAG topological sorting, cyclic graph evaluation, and parameter matrix sweeps fuzzed with `Hypothesis`.

---

## Preferred Disclosure Language

Please submit all reports in **English** to ensure the fastest possible triage and response.

---

*This policy follows coordinated disclosure best practices. Last reviewed: 2026-09.*
