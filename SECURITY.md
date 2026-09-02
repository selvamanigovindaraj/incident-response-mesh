# Security Policy & Governance

## Overview

This document outlines the security policies, vulnerability SLAs, and governance workflows for the `incident-response-mesh` repository. Security is treated with a fail-closed posture across all automated checks and continuous integration pipelines.

---

## 1. Secrets Hygiene: Zero-Tolerance Policy

This repository enforces a strict **zero-tolerance policy** for committed secrets, credentials, and sensitive tokens.

- **Automated Scanning:** All code is scanned locally prior to commit via `gitleaks` pre-commit hooks and centrally on all pull requests via CI (`gitleaks-action`).
- **Fail-Closed:** Gitleaks scans are configured to fail immediately upon finding any potential secret. Warning-only or advisory modes are not permitted.
- **Prohibited Data:** No API keys, cloud provider credentials, private keys, database passwords, webhook tokens, or certificates may be committed in plaintext under any circumstance.
- **Incident Response for Leaked Secrets:** If a secret is committed (even in a branch or PR), it must be treated as compromised immediately. The credential must be rotated and revoked at the provider immediately; simply rewriting git history or deleting the commit is not sufficient.

---

## 2. Vulnerability Management & SLAs

All application dependencies, container images, and Infrastructure-as-Code (IaC) configurations are continuously scanned for known security vulnerabilities via `pip-audit` and `trivy`.

### Severity Classifications & SLAs

| Severity | Action Required | Remediation SLA |
| :--- | :--- | :--- |
| **CRITICAL** | Must be upgraded/patched immediately or formally suppressed | Within 7 days (or immediate suppression if upstream fix unavailable) |
| **HIGH** | Must be upgraded/patched or formally suppressed | Within 14 days (or suppression if upstream fix unavailable) |
| **MEDIUM / LOW** | Triage and address during regular maintenance cycles | Best effort / next sprint |

Any unaddressed `HIGH` or `CRITICAL` vulnerability without an active, unexpired entry in `security-suppressions.yaml` will fail CI scans once the Ratchet Date is reached.

---

## 3. Ratchet Date Policy

To allow existing baseline vulnerabilities to be identified and remediated without disrupting active work, an initial grace period is established.

- **Current Ratchet Date:** `2026-09-16` (14 days from initial policy establishment on 2026-09-02)
- **Pre-Ratchet Window (Before 2026-09-16):**
  - Unsuppressed HIGH and CRITICAL vulnerabilities will log prominent warnings during security audit runs.
  - Builds will succeed (`exit 0`), allowing teams to remediate dependencies or file formal suppressions.
- **Post-Ratchet Enforcement (On or after 2026-09-16):**
  - All security audit scans become strictly **fail-closed**.
  - Any unsuppressed HIGH or CRITICAL vulnerability will cause CI builds to fail immediately (`exit 1`).

---

## 4. Time-Bound Vulnerability Suppressions Workflow

When a vulnerability cannot be resolved immediately (e.g., no upstream patch exists yet, or a major breaking upgrade requires planning), a **time-bound suppression** may be requested.

### Governance Rules for Suppressions

1. **Explicit Expiry:** Every suppression must have a concrete `expires_on` date in `YYYY-MM-DD` format (typically not exceeding 30 days).
2. **Fail-Closed on Expiration:** The security audit tooling verifies that no suppression has passed its `expires_on` date relative to the current UTC date. If an expired suppression exists in `security-suppressions.yaml`, the audit fails immediately with `exit 1`.
3. **Justification Required:** Every entry must document a clear, auditable `reason` explaining why immediate remediation is not viable and what compensating controls exist.
4. **Peer Review:** Changes to `security-suppressions.yaml` require standard pull request review and approval.

### Suppression Schema & Example

Suppressions are defined in `security-suppressions.yaml` at the repository root:

```yaml
suppressions:
  - id: "CVE-2026-12345"
    package: "example-library"
    reason: "Upstream patch pending release in v2.1.1; feature path not exposed to untrusted inputs"
    expires_on: "2026-10-02"
    suppressed_by: "username"
```

### Adding a Suppression

1. Verify the vulnerability details and confirm that an immediate fix is not available.
2. Edit `security-suppressions.yaml` and append the new entry under `suppressions`.
3. Set `expires_on` to a future date (maximum 30 days recommended).
4. Provide a thorough explanation in `reason`.
5. Submit a pull request detailing the risk assessment.

---

## 5. Reporting a Security Vulnerability

If you discover a security vulnerability in this project, please report it responsibly:

- Do **not** open a public GitHub issue.
- Contact the maintainers directly via repository security advisories or designated security contacts.
- Provide full reproduction steps, affected versions, and potential impact.
