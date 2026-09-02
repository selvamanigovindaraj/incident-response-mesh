import os
import sys
import tempfile
import yaml
import pytest
from pydantic import ValidationError

# Ensure root of repo is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scenarios")))

from scenarios.schema import RootCause, ScenarioLabel
from scenarios.validate import main as validate_main


def test_root_cause_valid():
    rc = RootCause(component="kafka", failure_mode="oom_kill")
    assert rc.component == "kafka"
    assert rc.failure_mode == "oom_kill"


def test_root_cause_missing_field():
    with pytest.raises(ValidationError):
        RootCause(component="kafka")


def test_scenario_label_valid():
    data = {
        "scenario_id": "infra-pod-oom",
        "category": "infra",
        "manifests": ["scenarios/manifests/infra-pod-oom.yaml"],
        "root_cause": {
            "component": "kafka",
            "failure_mode": "oom_kill",
        },
        "expected_severity": "critical",
        "expected_alerts": ["KubePodCrashLooping"],
        "red_herring_signals": [],
        "valid_remediations": ["Increase memory limit for kafka statefulset"],
        "duration_seconds": 60,
        "notes": "Test scenario note",
    }
    label = ScenarioLabel(**data)
    assert label.scenario_id == "infra-pod-oom"
    assert label.category == "infra"
    assert label.expected_severity == "critical"
    assert label.notes == "Test scenario note"
    assert label.duration_seconds == 60


def test_scenario_label_notes_optional():
    data = {
        "scenario_id": "network-api-latency",
        "category": "network",
        "manifests": ["scenarios/manifests/network-api-latency.yaml"],
        "root_cause": {
            "component": "checkout",
            "failure_mode": "high_latency",
        },
        "expected_severity": "warning",
        "expected_alerts": ["CheckoutServiceHighLatency"],
        "red_herring_signals": [],
        "valid_remediations": ["Investigate checkout service performance"],
        "duration_seconds": 60,
    }
    label = ScenarioLabel(**data)
    assert label.notes is None


@pytest.mark.parametrize("category", ["infra", "network", "app", "compound"])
def test_scenario_label_valid_categories(category):
    data = {
        "scenario_id": f"{category}-test",
        "category": category,
        "manifests": [],
        "root_cause": {"component": "comp", "failure_mode": "fail"},
        "expected_severity": "warning",
        "expected_alerts": [],
        "red_herring_signals": [],
        "valid_remediations": [],
        "duration_seconds": 30,
    }
    label = ScenarioLabel(**data)
    assert label.category == category


def test_scenario_label_invalid_category():
    data = {
        "scenario_id": "invalid-cat",
        "category": "database",
        "manifests": [],
        "root_cause": {"component": "db", "failure_mode": "crash"},
        "expected_severity": "warning",
        "expected_alerts": [],
        "red_herring_signals": [],
        "valid_remediations": [],
        "duration_seconds": 30,
    }
    with pytest.raises(ValidationError):
        ScenarioLabel(**data)


@pytest.mark.parametrize("severity", ["critical", "warning"])
def test_scenario_label_valid_severities(severity):
    data = {
        "scenario_id": f"sev-{severity}",
        "category": "infra",
        "manifests": [],
        "root_cause": {"component": "comp", "failure_mode": "fail"},
        "expected_severity": severity,
        "expected_alerts": [],
        "red_herring_signals": [],
        "valid_remediations": [],
        "duration_seconds": 30,
    }
    label = ScenarioLabel(**data)
    assert label.expected_severity == severity


def test_scenario_label_invalid_severity():
    data = {
        "scenario_id": "invalid-sev",
        "category": "infra",
        "manifests": [],
        "root_cause": {"component": "comp", "failure_mode": "fail"},
        "expected_severity": "info",
        "expected_alerts": [],
        "red_herring_signals": [],
        "valid_remediations": [],
        "duration_seconds": 30,
    }
    with pytest.raises(ValidationError):
        ScenarioLabel(**data)


def test_validate_script_success(monkeypatch, tmp_path):
    labels_dir = tmp_path / "scenarios" / "labels"
    labels_dir.mkdir(parents=True)
    
    valid_label = {
        "scenario_id": "infra-pod-oom",
        "category": "infra",
        "manifests": ["scenarios/manifests/infra-pod-oom.yaml"],
        "root_cause": {
            "component": "kafka",
            "failure_mode": "oom_kill",
        },
        "expected_severity": "critical",
        "expected_alerts": ["KubePodCrashLooping"],
        "red_herring_signals": [],
        "valid_remediations": ["Increase memory limit for kafka statefulset"],
        "duration_seconds": 60,
    }
    with open(labels_dir / "infra-pod-oom.yaml", "w") as f:
        yaml.dump(valid_label, f)
        
    monkeypatch.chdir(tmp_path)
    # Should run without sys.exit(1)
    validate_main()


def test_validate_script_failure_on_invalid_yaml(monkeypatch, tmp_path):
    labels_dir = tmp_path / "scenarios" / "labels"
    labels_dir.mkdir(parents=True)
    
    invalid_label = {
        "scenario_id": "bad-scenario",
        "category": "invalid_category",
    }
    with open(labels_dir / "bad.yaml", "w") as f:
        yaml.dump(invalid_label, f)
        
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        validate_main()
    assert exc_info.value.code == 1


def test_validate_script_missing_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        validate_main()
    assert exc_info.value.code == 1


def test_infra_scenarios_exist_and_valid():
    infra_scenarios = [
        "infra-pod-oom",
        "infra-node-cpu",
        "infra-pvc-full",
        "infra-pod-eviction",
    ]
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    labels_dir = os.path.join(repo_root, "scenarios", "labels")

    for sc_id in infra_scenarios:
        label_file = os.path.join(labels_dir, f"{sc_id}.yaml")
        assert os.path.exists(label_file), f"Missing label file for {sc_id}"
        with open(label_file, "r") as f:
            data = yaml.safe_load(f)
        label = ScenarioLabel(**data)
        assert label.scenario_id == sc_id
        assert label.category == "infra"
        for manifest in label.manifests:
            manifest_path = os.path.join(repo_root, manifest)
            assert os.path.exists(manifest_path), f"Manifest {manifest} does not exist"


def test_network_scenarios_exist_and_valid():
    network_scenarios = [
        "network-db-partition",
        "network-api-latency",
        "network-dns-failure",
        "network-packet-loss",
    ]
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    labels_dir = os.path.join(repo_root, "scenarios", "labels")

    for sc_id in network_scenarios:
        label_file = os.path.join(labels_dir, f"{sc_id}.yaml")
        assert os.path.exists(label_file), f"Missing label file for {sc_id}"
        with open(label_file, "r") as f:
            data = yaml.safe_load(f)
        label = ScenarioLabel(**data)
        assert label.scenario_id == sc_id
        assert label.category == "network"
        for manifest in label.manifests:
            manifest_path = os.path.join(repo_root, manifest)
            assert os.path.exists(manifest_path), f"Manifest {manifest} does not exist"


