# Supply-Chain & Secrets Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish baseline supply-chain and secrets hygiene using Gitleaks, Trivy, and Pip-Audit with a custom expiry-driven suppression workflow.

**Spec:** `docs/superpowers/specs/2026-09-02-supply-chain-hygiene-design.md`

## Global Constraints
- **Speed:** Dependency audits and Trivy IaC scans must only run when their respective target files (`uv.lock` and `infra/`) change in CI.
- **Fail-Closed Secrets:** Gitleaks must never warn; it must always fail.
- **Fail-Closed Suppressions:** The security wrapper must hard-fail immediately if any suppression entry's `expires_on` date is in the past relative to the current UTC date.

---

### Task 1: Secrets Hygiene (Gitleaks)

**Files:**
- Modify: `.pre-commit-config.yaml`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Pre-commit Hook**
  Add the `gitleaks` pre-commit hook to `.pre-commit-config.yaml` to scan commits locally.
  ```yaml
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.2
    hooks:
      - id: gitleaks
  ```

- [ ] **Step 2: CI Integration**
  Add a `security-audit` job to `.github/workflows/ci.yml` (running before the `detect-changes` matrix) that uses `zricethezav/gitleaks-action`.
  
- [ ] **Step 3: Verification (Fake Secret)**
  - Create a temporary dummy file containing a fake AWS key (e.g., `AKIAIOSFODNN7EXAMPLE`).
  - Verify that running `pre-commit run --all-files` catches the secret and fails.
  - Delete the dummy file before committing your final work.

- [ ] **Step 4: Commit**
  Commit the `.pre-commit-config.yaml` and `ci.yml` changes.

---

### Task 2: Policy & Governance Foundation

**Files:**
- Create: `SECURITY.md`
- Create: `security-suppressions.yaml`

- [ ] **Step 1: Write `SECURITY.md`**
  Draft the security policy at the repository root. Include:
  - Zero-tolerance policy for secrets.
  - Vulnerability SLA (HIGH/CRITICAL must be fixed or formally suppressed).
  - Explicit documentation of the Ratchet Date (Set it to 14 days from today).
  - The workflow for adding a time-bound suppression entry.

- [ ] **Step 2: Create `security-suppressions.yaml`**
  Create the empty allowlist at the repository root using the defined schema:
  ```yaml
  suppressions: []
  ```

- [ ] **Step 3: Commit**
  Commit both governance files.

---

### Task 3: The Custom Security Wrapper (`scripts/security-audit.py`)

**Files:**
- Create: `scripts/security-audit.py`
- Modify: `pyproject.toml` (Add `pip-audit` to global dev dependencies)

- [ ] **Step 1: Add dependencies**
  Add `pip-audit` to the root workspace `pyproject.toml` dev dependencies and run `uv sync`.

- [ ] **Step 2: Write `scripts/security-audit.py`**
  Write a script that:
  - Loads `security-suppressions.yaml`.
  - Checks if any `expires_on` date is < `datetime.now(UTC)`. If so, print error and `sys.exit(1)`.
  - Runs `uv export --format requirements-txt | pip-audit -r /dev/stdin -f json` via `subprocess`.
  - Runs `trivy fs infra/ --format json` via `subprocess`.
  - Parses the JSON outputs to find CVEs.
  - Filters out any CVEs present in the unexpired suppressions list.
  - If unsuppressed CVEs exist:
    - Check the hardcoded `RATCHET_DATE` (14 days from today).
    - If today < `RATCHET_DATE`: Print warnings and `sys.exit(0)`.
    - If today >= `RATCHET_DATE`: Print errors and `sys.exit(1)`.

- [ ] **Step 3: Commit**
  Commit the script and root lockfile changes.

---

### Task 4: CI Pipeline Integration (Vulnerability Scanning)

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Conditional Audits in CI**
  Update the `detect-changes` job in `ci.yml` to also detect changes in `uv.lock`, `infra/**`, and `security-suppressions.yaml`.
  Update the `security-audit` job to conditionally run `scripts/security-audit.py` if those files changed. (Ensure the job installs `uv`, `trivy`, and Python).

- [ ] **Step 2: Container Image Scanning**
  Update the existing `docker-build` job in `ci.yml` to run `trivy image hello-world:test --exit-code 1 --severity HIGH,CRITICAL` immediately after building the image.

- [ ] **Step 3: Baseline Triage**
  Run `trivy` locally on the `hello-world` image. If there are any baseline HIGH/CRITICAL vulnerabilities that cannot be easily fixed, add them to `security-suppressions.yaml` with an expiry date 30 days out and a justification.

- [ ] **Step 4: Commit**
  Commit the final CI modifications and baseline suppressions.
