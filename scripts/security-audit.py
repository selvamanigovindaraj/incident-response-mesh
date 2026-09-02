#!/usr/bin/env python3
"""Security Audit Script

Performs vulnerability and misconfiguration scanning for dependencies (via pip-audit)
and infrastructure configurations (via trivy). Cross-references findings against
security-suppressions.yaml, enforces strict expiration on suppressions (fail-closed),
and enforces a ratchet date policy for unsuppressed findings.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

# Ratchet date: 14 days from initial policy establishment on 2026-09-02
RATCHET_DATE = date(2026, 9, 16)


@dataclass
class Finding:
    """Represents a vulnerability or misconfiguration finding."""

    source: str  # "pip-audit" or "trivy"
    id: str
    aliases: list[str] = field(default_factory=list)
    package: str = ""
    version: str = ""
    severity: str = ""
    target: str = ""
    description: str = ""

    def matches_id(self, supp_id: str) -> bool:
        """Check if finding ID or any alias matches suppression ID."""
        target_id = supp_id.strip().upper()
        if self.id.strip().upper() == target_id:
            return True
        return any(alias.strip().upper() == target_id for alias in self.aliases)


@dataclass
class Suppression:
    """Represents a time-bound vulnerability suppression entry."""

    id: str
    expires_on: date
    reason: str
    package: str = ""
    suppressed_by: str = ""

    def is_expired(self, current_date: date | None = None) -> bool:
        """Check if suppression has expired relative to current UTC date."""
        if current_date is None:
            current_date = datetime.now(UTC).date()
        return self.expires_on < current_date


def parse_date(date_val: Any) -> date:
    """Parse a date value from string, date, or datetime."""
    if isinstance(date_val, datetime):
        return date_val.date()
    if isinstance(date_val, date):
        return date_val
    if isinstance(date_val, str):
        cleaned = date_val.strip()
        if "T" in cleaned:
            return datetime.fromisoformat(cleaned).date()
        return date.fromisoformat(cleaned)
    raise ValueError(f"Invalid date format: {date_val!r}")


def load_suppressions(
    file_path: Path, current_date: date | None = None
) -> tuple[list[Suppression], list[Suppression]]:
    """Load suppressions from YAML file and partition into (active, expired).

    Returns:
        tuple[active_suppressions, expired_suppressions]
    """
    if not file_path.exists():
        return [], []

    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    raw_suppressions = data.get("suppressions") or []
    active: list[Suppression] = []
    expired: list[Suppression] = []

    if current_date is None:
        current_date = datetime.now(UTC).date()

    for item in raw_suppressions:
        if not isinstance(item, dict):
            continue
        supp_id = str(item.get("id", "")).strip()
        if not supp_id:
            continue
        expires_on_raw = item.get("expires_on")
        if not expires_on_raw:
            raise ValueError(
                f"Suppression '{supp_id}' is missing required 'expires_on' field."
            )
        expires_on = parse_date(expires_on_raw)
        reason = str(item.get("reason", "")).strip()
        package = str(item.get("package", "")).strip()
        suppressed_by = str(item.get("suppressed_by", "")).strip()

        supp = Suppression(
            id=supp_id,
            expires_on=expires_on,
            reason=reason,
            package=package,
            suppressed_by=suppressed_by,
        )

        if supp.is_expired(current_date):
            expired.append(supp)
        else:
            active.append(supp)

    return active, expired


def run_pip_audit(repo_root: Path) -> list[Finding]:
    """Export dependencies and run pip-audit, returning list of Findings."""
    uv_cmd = shutil.which("uv") or "uv"
    uv_res = subprocess.run(
        [uv_cmd, "export", "--format", "requirements-txt"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if uv_res.returncode != 0:
        print(f"[ERROR] 'uv export' failed:\n{uv_res.stderr}", file=sys.stderr)
        raise RuntimeError(f"uv export failed with return code {uv_res.returncode}")

    pip_audit_cmd = shutil.which("pip-audit")
    cmd = (
        [pip_audit_cmd, "-r", "/dev/stdin", "-f", "json"]
        if pip_audit_cmd
        else [sys.executable, "-m", "pip_audit", "-r", "/dev/stdin", "-f", "json"]
    )

    audit_res = subprocess.run(
        cmd,
        input=uv_res.stdout,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    # pip-audit exits with 1 when vulnerabilities exist, but outputs JSON to stdout
    if not audit_res.stdout.strip():
        if audit_res.returncode != 0:
            print(
                f"[ERROR] 'pip-audit' execution error:\n{audit_res.stderr}",
                file=sys.stderr,
            )
            raise RuntimeError(
                f"pip-audit failed with return code {audit_res.returncode}"
            )
        return []

    try:
        data = json.loads(audit_res.stdout)
    except json.JSONDecodeError as exc:
        print(
            f"[ERROR] Failed to parse pip-audit JSON output: {exc}\nOutput was:\n{audit_res.stdout}",
            file=sys.stderr,
        )
        raise RuntimeError(f"Invalid pip-audit JSON: {exc}") from exc

    return parse_pip_audit_json(data)


def parse_pip_audit_json(data: dict[str, Any]) -> list[Finding]:
    """Parse pip-audit JSON object into a list of Finding objects."""
    findings: list[Finding] = []
    dependencies = data.get("dependencies", [])
    for dep in dependencies:
        pkg_name = dep.get("name", "")
        pkg_version = dep.get("version", "")
        vulns = dep.get("vulns", [])
        for vuln in vulns:
            vuln_id = vuln.get("id", "")
            aliases = vuln.get("aliases", []) or []
            desc = vuln.get("description", "")
            findings.append(
                Finding(
                    source="pip-audit",
                    id=vuln_id,
                    aliases=aliases,
                    package=pkg_name,
                    version=pkg_version,
                    severity=vuln.get("severity", ""),
                    target="dependencies",
                    description=desc,
                )
            )
    return findings


def run_trivy(repo_root: Path, target_dir: str = "infra/") -> list[Finding]:
    """Run trivy fs on infra directory and return list of Findings."""
    trivy_path = shutil.which("trivy")
    if not trivy_path:
        print(
            "[WARN] 'trivy' executable not found on PATH. Skipping trivy fs scan.",
            file=sys.stderr,
        )
        return []

    infra_path = repo_root / target_dir
    if not infra_path.exists():
        return []

    trivy_res = subprocess.run(
        [trivy_path, "fs", target_dir, "--format", "json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    if not trivy_res.stdout.strip():
        if trivy_res.returncode != 0:
            print(
                f"[ERROR] 'trivy fs' failed with code {trivy_res.returncode}:\n{trivy_res.stderr}",
                file=sys.stderr,
            )
            raise RuntimeError(
                f"trivy fs failed with return code {trivy_res.returncode}"
            )
        return []

    try:
        data = json.loads(trivy_res.stdout)
    except json.JSONDecodeError as exc:
        print(
            f"[ERROR] Failed to parse trivy JSON output: {exc}\nOutput was:\n{trivy_res.stdout}",
            file=sys.stderr,
        )
        raise RuntimeError(f"Invalid trivy JSON: {exc}") from exc

    return parse_trivy_json(data)


def parse_trivy_json(data: dict[str, Any]) -> list[Finding]:
    """Parse trivy JSON object into a list of Finding objects."""
    findings: list[Finding] = []
    results = data.get("Results") or []
    for res in results:
        target = res.get("Target", "")

        # Vulnerabilities
        for vuln in res.get("Vulnerabilities", []) or []:
            vuln_id = vuln.get("VulnerabilityID") or vuln.get("id", "")
            aliases = vuln.get("Aliases", []) or []
            pkg = vuln.get("PkgName", "")
            ver = vuln.get("InstalledVersion", "")
            sev = vuln.get("Severity", "")
            title = vuln.get("Title") or vuln.get("Description", "")
            findings.append(
                Finding(
                    source="trivy",
                    id=vuln_id,
                    aliases=aliases,
                    package=pkg,
                    version=ver,
                    severity=sev,
                    target=target,
                    description=title,
                )
            )

        # Misconfigurations
        for misc in res.get("Misconfigurations", []) or []:
            misc_id = misc.get("ID") or misc.get("AVDID", "")
            aliases = []
            if misc.get("AVDID") and misc.get("AVDID") != misc_id:
                aliases.append(misc.get("AVDID"))
            if misc.get("ID") and misc.get("ID") != misc_id:
                aliases.append(misc.get("ID"))
            sev = misc.get("Severity", "")
            title = misc.get("Title") or misc.get("Description", "")
            findings.append(
                Finding(
                    source="trivy",
                    id=misc_id,
                    aliases=aliases,
                    package=target,
                    version="",
                    severity=sev,
                    target=target,
                    description=title,
                )
            )

    return findings


def filter_findings(
    findings: list[Finding], active_suppressions: list[Suppression]
) -> tuple[list[Finding], list[tuple[Finding, Suppression]]]:
    """Filter findings against active suppressions.

    Returns:
        tuple[unsuppressed_findings, list_of_(finding, matched_suppression)]
    """
    unsuppressed: list[Finding] = []
    suppressed: list[tuple[Finding, Suppression]] = []

    for finding in findings:
        matched_supp = None
        for supp in active_suppressions:
            if finding.matches_id(supp.id):
                matched_supp = supp
                break
        if matched_supp:
            suppressed.append((finding, matched_supp))
        else:
            unsuppressed.append(finding)

    return unsuppressed, suppressed


def audit(
    repo_root: Path,
    suppressions_file: Path | None = None,
    current_date: date | None = None,
    ratchet_date: date | None = None,
) -> int:
    """Execute complete security audit workflow.

    Returns exit code (0 for success/grace warning, 1 for errors/expired/ratchet-failed).
    """
    if suppressions_file is None:
        suppressions_file = repo_root / "security-suppressions.yaml"

    if current_date is None:
        current_date = datetime.now(UTC).date()

    if ratchet_date is None:
        ratchet_date = RATCHET_DATE

    print("==================================================")
    print("🔒 Running Security Audit")
    print(f"📅 Current Date (UTC): {current_date}")
    print(f"📅 Ratchet Date:        {ratchet_date}")
    print(f"📋 Suppressions File:  {suppressions_file}")
    print("==================================================")

    # 1. Load and check suppressions
    try:
        active_suppressions, expired_suppressions = load_suppressions(
            suppressions_file, current_date=current_date
        )
    except (yaml.YAMLError, ValueError, OSError) as exc:
        print(f"\n❌ [ERROR] Failed to load suppressions: {exc}", file=sys.stderr)
        return 1

    if expired_suppressions:
        print(
            "\n❌ [FAIL-CLOSED] Expired suppressions detected in security-suppressions.yaml:",
            file=sys.stderr,
        )
        for exp in expired_suppressions:
            print(
                f"   - ID: {exp.id} | Expired on: {exp.expires_on} (Current: {current_date}) | Reason: {exp.reason}",
                file=sys.stderr,
            )
        print(
            "\nAll suppressions must have valid, future 'expires_on' dates. Remove or renew expired entries.",
            file=sys.stderr,
        )
        return 1

    print(
        f"✅ Suppressions check: {len(active_suppressions)} active suppression(s), 0 expired."
    )

    # 2. Run scans
    all_findings: list[Finding] = []

    print("\n🔍 Running dependency audit (uv export | pip-audit)...")
    try:
        pip_findings = run_pip_audit(repo_root)
        print(f"   pip-audit found {len(pip_findings)} vulnerability finding(s).")
        all_findings.extend(pip_findings)
    except (RuntimeError, OSError) as exc:
        print(f"\n❌ [ERROR] pip-audit scan failed: {exc}", file=sys.stderr)
        return 1

    print("🔍 Running filesystem scan (trivy fs infra/)...")
    try:
        trivy_findings = run_trivy(repo_root)
        print(f"   trivy found {len(trivy_findings)} finding(s).")
        all_findings.extend(trivy_findings)
    except (RuntimeError, OSError) as exc:
        print(f"\n❌ [ERROR] trivy scan failed: {exc}", file=sys.stderr)
        return 1

    # 3. Filter findings
    unsuppressed, suppressed = filter_findings(all_findings, active_suppressions)

    if suppressed:
        print(f"\n🛡️  Suppressed Findings ({len(suppressed)}):")
        for finding, supp in suppressed:
            print(
                f"   - [{finding.source.upper()}] {finding.id} ({finding.package} {finding.version}) -> Suppressed until {supp.expires_on}: {supp.reason}"
            )

    if not unsuppressed:
        print(
            "\n✨ Security audit passed! No unsuppressed vulnerabilities or misconfigurations found."
        )
        return 0

    # 4. Handle unsuppressed findings based on Ratchet Date
    print(f"\n⚠️  Found {len(unsuppressed)} UNSUPPRESSED finding(s):")
    for finding in unsuppressed:
        sev_str = f"[{finding.severity}] " if finding.severity else ""
        print(
            f"   - [{finding.source.upper()}] {sev_str}{finding.id} in {finding.package or finding.target} {finding.version}"
        )
        if finding.description:
            summary = finding.description.split("\n")[0][:100]
            print(f"     Description: {summary}")

    if current_date < ratchet_date:
        print(
            f"\n⚠️  [WARN-ONLY MODE] Grace period active (Today {current_date} < Ratchet Date {ratchet_date})."
        )
        print(
            "   Please remediate these vulnerabilities or add time-bound suppressions before the ratchet date."
        )
        return 0
    else:
        print(
            f"\n❌ [FAIL-CLOSED] Ratchet date has passed (Today {current_date} >= Ratchet Date {ratchet_date}).",
            file=sys.stderr,
        )
        print(
            "   Unsuppressed HIGH/CRITICAL vulnerabilities block the build. Fix or formally suppress them.",
            file=sys.stderr,
        )
        return 1


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Security Audit Wrapper (pip-audit + trivy)"
    )
    parser.add_argument(
        "--suppressions",
        type=Path,
        default=None,
        help="Path to security-suppressions.yaml (defaults to repo root file)",
    )
    parser.add_argument(
        "--ratchet-date",
        type=str,
        default=None,
        help="Override ratchet date for testing (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--current-date",
        type=str,
        default=None,
        help="Override current date for testing (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    suppressions_file = args.suppressions or (repo_root / "security-suppressions.yaml")

    current_date = (
        parse_date(args.current_date) if args.current_date else datetime.now(UTC).date()
    )
    ratchet_date = parse_date(args.ratchet_date) if args.ratchet_date else RATCHET_DATE

    return audit(
        repo_root=repo_root,
        suppressions_file=suppressions_file,
        current_date=current_date,
        ratchet_date=ratchet_date,
    )


if __name__ == "__main__":
    sys.exit(main())
