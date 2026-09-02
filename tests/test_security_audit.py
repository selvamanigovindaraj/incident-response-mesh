"""Unit and integration tests for scripts/security-audit.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add repo root to sys.path to import security-audit script
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

spec = importlib.util.spec_from_file_location(
    "security_audit", REPO_ROOT / "scripts" / "security-audit.py"
)
assert spec is not None and spec.loader is not None
security_audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = security_audit
spec.loader.exec_module(security_audit)

Finding = security_audit.Finding
Suppression = security_audit.Suppression
parse_date = security_audit.parse_date
load_suppressions = security_audit.load_suppressions
parse_pip_audit_json = security_audit.parse_pip_audit_json
parse_trivy_json = security_audit.parse_trivy_json
filter_findings = security_audit.filter_findings
audit = security_audit.audit
RATCHET_DATE = security_audit.RATCHET_DATE


class TestParseDate:
    """Test date parsing utility."""

    def test_parse_iso_string(self) -> None:
        assert parse_date("2026-09-02") == date(2026, 9, 2)
        assert parse_date("2026-12-31") == date(2026, 12, 31)

    def test_parse_timestamp_string(self) -> None:
        assert parse_date("2026-09-02T15:30:00Z") == date(2026, 9, 2)

    def test_parse_date_and_datetime_objects(self) -> None:
        d = date(2026, 9, 16)
        dt = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
        assert parse_date(d) == d
        assert parse_date(dt) == d

    def test_parse_invalid_date(self) -> None:
        with pytest.raises(ValueError, match="Invalid date format"):
            parse_date(12345)


class TestFindingMatching:
    """Test Finding dataclass matching."""

    def test_matches_exact_id(self) -> None:
        finding = Finding(source="pip-audit", id="CVE-2026-0001")
        assert finding.matches_id("CVE-2026-0001")
        assert finding.matches_id("cve-2026-0001")
        assert not finding.matches_id("CVE-2026-0002")

    def test_matches_alias(self) -> None:
        finding = Finding(
            source="pip-audit",
            id="PYSEC-2026-9999",
            aliases=["GHSA-xxxx-yyyy", "CVE-2026-1111"],
        )
        assert finding.matches_id("PYSEC-2026-9999")
        assert finding.matches_id("CVE-2026-1111")
        assert finding.matches_id("ghsa-xxxx-yyyy")
        assert not finding.matches_id("CVE-2026-2222")


class TestLoadSuppressions:
    """Test loading and expiration validation of security-suppressions.yaml."""

    def test_load_empty_file(self, tmp_path: Path) -> None:
        file = tmp_path / "suppressions.yaml"
        file.write_text("suppressions: []\n")
        active, expired = load_suppressions(file, current_date=date(2026, 9, 2))
        assert active == []
        assert expired == []

    def test_load_nonexistent_file(self, tmp_path: Path) -> None:
        file = tmp_path / "does-not-exist.yaml"
        active, expired = load_suppressions(file, current_date=date(2026, 9, 2))
        assert active == []
        assert expired == []

    def test_load_active_and_expired_suppressions(self, tmp_path: Path) -> None:
        file = tmp_path / "suppressions.yaml"
        file.write_text(
            """
suppressions:
  - id: "CVE-2026-ACTIVE"
    package: "requests"
    reason: "Upstream patch pending"
    expires_on: "2026-10-01"
    suppressed_by: "alice"
  - id: "CVE-2026-EXPIRED"
    package: "urllib3"
    reason: "Old issue"
    expires_on: "2026-09-01"
    suppressed_by: "bob"
  - id: "CVE-2026-TODAY"
    package: "foo"
    reason: "Expires today"
    expires_on: "2026-09-02"
    suppressed_by: "carol"
"""
        )
        current = date(2026, 9, 2)
        active, expired = load_suppressions(file, current_date=current)

        assert len(active) == 2
        active_ids = {s.id for s in active}
        assert active_ids == {"CVE-2026-ACTIVE", "CVE-2026-TODAY"}

        assert len(expired) == 1
        assert expired[0].id == "CVE-2026-EXPIRED"
        assert expired[0].expires_on == date(2026, 9, 1)

    def test_missing_expires_on_raises_error(self, tmp_path: Path) -> None:
        file = tmp_path / "suppressions.yaml"
        file.write_text(
            """
suppressions:
  - id: "CVE-2026-INVALID"
    reason: "Missing expires_on"
"""
        )
        with pytest.raises(ValueError, match="missing required 'expires_on'"):
            load_suppressions(file, current_date=date(2026, 9, 2))


class TestParsePipAuditJson:
    """Test parsing pip-audit output JSON."""

    def test_parse_clean_output(self) -> None:
        data = {
            "dependencies": [{"name": "safe-pkg", "version": "1.0.0", "vulns": []}],
            "fixes": [],
        }
        findings = parse_pip_audit_json(data)
        assert findings == []

    def test_parse_vulnerable_output(self) -> None:
        data = {
            "dependencies": [
                {
                    "name": "vulnerable-pkg",
                    "version": "1.2.3",
                    "vulns": [
                        {
                            "id": "PYSEC-2026-0001",
                            "aliases": ["CVE-2026-12345", "GHSA-abcd-1234"],
                            "description": "Buffer overflow",
                            "fix_versions": ["1.2.4"],
                        }
                    ],
                }
            ]
        }
        findings = parse_pip_audit_json(data)
        assert len(findings) == 1
        f = findings[0]
        assert f.source == "pip-audit"
        assert f.id == "PYSEC-2026-0001"
        assert f.aliases == ["CVE-2026-12345", "GHSA-abcd-1234"]
        assert f.package == "vulnerable-pkg"
        assert f.version == "1.2.3"
        assert f.description == "Buffer overflow"


class TestParseTrivyJson:
    """Test parsing trivy fs output JSON."""

    def test_parse_clean_output(self) -> None:
        data = {"SchemaVersion": 2, "Results": []}
        findings = parse_trivy_json(data)
        assert findings == []

    def test_parse_trivy_vulns_and_misconfigurations(self) -> None:
        data = {
            "SchemaVersion": 2,
            "Results": [
                {
                    "Target": "infra/k3d.yaml",
                    "Vulnerabilities": [
                        {
                            "VulnerabilityID": "CVE-2026-7890",
                            "PkgName": "k8s-dep",
                            "InstalledVersion": "0.1.0",
                            "Severity": "HIGH",
                            "Title": "Denial of service",
                        }
                    ],
                    "Misconfigurations": [
                        {
                            "ID": "KSV001",
                            "AVDID": "AVD-KSV-0001",
                            "Severity": "CRITICAL",
                            "Title": "Privileged container allowed",
                        }
                    ],
                }
            ],
        }
        findings = parse_trivy_json(data)
        assert len(findings) == 2

        vuln_f = next(f for f in findings if f.id == "CVE-2026-7890")
        assert vuln_f.source == "trivy"
        assert vuln_f.severity == "HIGH"
        assert vuln_f.package == "k8s-dep"
        assert vuln_f.target == "infra/k3d.yaml"

        misc_f = next(f for f in findings if f.id == "KSV001")
        assert misc_f.source == "trivy"
        assert misc_f.severity == "CRITICAL"
        assert "AVD-KSV-0001" in misc_f.aliases


class TestFilterFindings:
    """Test filtering findings against active suppressions."""

    def test_suppressed_finding_by_cve_alias(self) -> None:
        findings = [
            Finding(
                source="pip-audit",
                id="PYSEC-2026-0001",
                aliases=["CVE-2026-12345"],
                package="pkg-a",
            ),
            Finding(
                source="pip-audit",
                id="CVE-2026-99999",
                package="pkg-b",
            ),
        ]
        active_suppressions = [
            Suppression(
                id="CVE-2026-12345",
                expires_on=date(2026, 10, 1),
                reason="Temporary suppression",
            )
        ]

        unsuppressed, suppressed = filter_findings(findings, active_suppressions)

        assert len(suppressed) == 1
        assert suppressed[0][0].id == "PYSEC-2026-0001"
        assert suppressed[0][1].id == "CVE-2026-12345"

        assert len(unsuppressed) == 1
        assert unsuppressed[0].id == "CVE-2026-99999"


class TestAuditWorkflow:
    """Test the complete audit function with mocked scans and ratchet date behavior."""

    @patch("security_audit.run_pip_audit")
    @patch("security_audit.run_trivy")
    def test_clean_audit_passes(
        self, mock_trivy: MagicMock, mock_pip: MagicMock, tmp_path: Path
    ) -> None:
        mock_pip.return_value = []
        mock_trivy.return_value = []

        supp_file = tmp_path / "suppressions.yaml"
        supp_file.write_text("suppressions: []\n")

        exit_code = audit(
            repo_root=REPO_ROOT,
            suppressions_file=supp_file,
            current_date=date(2026, 9, 2),
            ratchet_date=date(2026, 9, 16),
        )
        assert exit_code == 0

    @patch("security_audit.run_pip_audit")
    @patch("security_audit.run_trivy")
    def test_expired_suppression_fails_closed(
        self, mock_trivy: MagicMock, mock_pip: MagicMock, tmp_path: Path
    ) -> None:
        supp_file = tmp_path / "suppressions.yaml"
        supp_file.write_text(
            """
suppressions:
  - id: "CVE-2026-OLD"
    expires_on: "2026-09-01"
    reason: "Expired yesterday"
"""
        )

        exit_code = audit(
            repo_root=REPO_ROOT,
            suppressions_file=supp_file,
            current_date=date(2026, 9, 2),
            ratchet_date=date(2026, 9, 16),
        )
        assert exit_code == 1
        # Should fail before running scans
        mock_pip.assert_not_called()
        mock_trivy.assert_not_called()

    @patch("security_audit.run_pip_audit")
    @patch("security_audit.run_trivy")
    def test_unsuppressed_cve_pre_ratchet_warns_and_exits_0(
        self, mock_trivy: MagicMock, mock_pip: MagicMock, tmp_path: Path
    ) -> None:
        mock_pip.return_value = [
            Finding(
                source="pip-audit",
                id="CVE-2026-UNRESOLVED",
                package="pkg-x",
                version="1.0.0",
            )
        ]
        mock_trivy.return_value = []

        supp_file = tmp_path / "suppressions.yaml"
        supp_file.write_text("suppressions: []\n")

        # Today: 2026-09-02, Ratchet: 2026-09-16 (Pre-ratchet grace period)
        exit_code = audit(
            repo_root=REPO_ROOT,
            suppressions_file=supp_file,
            current_date=date(2026, 9, 2),
            ratchet_date=date(2026, 9, 16),
        )
        assert exit_code == 0

    @patch("security_audit.run_pip_audit")
    @patch("security_audit.run_trivy")
    def test_unsuppressed_cve_post_ratchet_fails_exit_1(
        self, mock_trivy: MagicMock, mock_pip: MagicMock, tmp_path: Path
    ) -> None:
        mock_pip.return_value = [
            Finding(
                source="pip-audit",
                id="CVE-2026-UNRESOLVED",
                package="pkg-x",
                version="1.0.0",
            )
        ]
        mock_trivy.return_value = []

        supp_file = tmp_path / "suppressions.yaml"
        supp_file.write_text("suppressions: []\n")

        # Today: 2026-09-16, Ratchet: 2026-09-16 (Post-ratchet fail-closed)
        exit_code = audit(
            repo_root=REPO_ROOT,
            suppressions_file=supp_file,
            current_date=date(2026, 9, 16),
            ratchet_date=date(2026, 9, 16),
        )
        assert exit_code == 1

    @patch("security_audit.run_pip_audit")
    @patch("security_audit.run_trivy")
    def test_suppressed_cve_post_ratchet_passes(
        self, mock_trivy: MagicMock, mock_pip: MagicMock, tmp_path: Path
    ) -> None:
        mock_pip.return_value = [
            Finding(
                source="pip-audit",
                id="CVE-2026-SUPPRESSED",
                package="pkg-x",
                version="1.0.0",
            )
        ]
        mock_trivy.return_value = []

        supp_file = tmp_path / "suppressions.yaml"
        supp_file.write_text(
            """
suppressions:
  - id: "CVE-2026-SUPPRESSED"
    expires_on: "2026-10-01"
    reason: "Documented suppression"
"""
        )

        # Today: 2026-09-16, Ratchet: 2026-09-16 (Finding is suppressed, so passes)
        exit_code = audit(
            repo_root=REPO_ROOT,
            suppressions_file=supp_file,
            current_date=date(2026, 9, 16),
            ratchet_date=date(2026, 9, 16),
        )
        assert exit_code == 0


class TestCLIExecution:
    """Integration tests running security-audit.py via subprocess."""

    def test_cli_help(self) -> None:
        res = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "security-audit.py"),
                "--help",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0
        assert "Security Audit Wrapper" in res.stdout

    def test_cli_expired_suppression(self, tmp_path: Path) -> None:
        supp_file = tmp_path / "suppressions.yaml"
        supp_file.write_text(
            """
suppressions:
  - id: "CVE-2026-EXPIRED"
    expires_on: "2026-09-01"
    reason: "Expired"
"""
        )
        res = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "security-audit.py"),
                "--suppressions",
                str(supp_file),
                "--current-date",
                "2026-09-02",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 1
        assert "Expired suppressions detected" in res.stderr
