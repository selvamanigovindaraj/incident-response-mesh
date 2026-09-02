import importlib.util
import os
import sys
import tempfile
import yaml
import pytest
from unittest.mock import MagicMock, patch

# Ensure root of repo is in sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

def load_run_scenario_module():
    script_path = os.path.join(REPO_ROOT, "scripts", "run-scenario.py")
    spec = importlib.util.spec_from_file_location("run_scenario", script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_scenario"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def run_scenario():
    return load_run_scenario_module()


def test_run_cmd_success(run_scenario):
    assert run_scenario.run_cmd(["echo", "test success"]) is True


def test_run_cmd_failure(run_scenario):
    assert run_scenario.run_cmd(["false"]) is False


def test_check_alerts_success_dict_format(run_scenario):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "status": "success",
        "data": {
            "alerts": [
                {
                    "state": "firing",
                    "labels": {"alertname": "KubePodCrashLooping"},
                },
                {
                    "state": "firing",
                    "labels": {"alertname": "RedHerringAlert"},
                },
            ]
        },
    }
    with patch("requests.get", return_value=mock_resp):
        res = run_scenario.check_alerts(["KubePodCrashLooping"], ["RedHerringAlert"])
        assert res is True


def test_check_alerts_success_list_format(run_scenario):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "status": "success",
        "data": [
            {
                "state": "firing",
                "labels": {"alertname": "KubePodCrashLooping"},
            },
        ],
    }
    with patch("requests.get", return_value=mock_resp):
        res = run_scenario.check_alerts(["KubePodCrashLooping"], [])
        assert res is True


def test_check_alerts_missing_expected(run_scenario):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "status": "success",
        "data": {
            "alerts": [
                {
                    "state": "firing",
                    "labels": {"alertname": "SomeOtherAlert"},
                }
            ]
        },
    }
    with patch("requests.get", return_value=mock_resp):
        res = run_scenario.check_alerts(["KubePodCrashLooping"], [])
        assert res is False


def test_check_alerts_missing_red_herring(run_scenario):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "status": "success",
        "data": {
            "alerts": [
                {
                    "state": "firing",
                    "labels": {"alertname": "KubePodCrashLooping"},
                }
            ]
        },
    }
    with patch("requests.get", return_value=mock_resp):
        res = run_scenario.check_alerts(["KubePodCrashLooping"], ["RedHerringAlert"])
        assert res is False


def test_check_alerts_ignores_non_firing(run_scenario):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "status": "success",
        "data": {
            "alerts": [
                {
                    "state": "pending",
                    "labels": {"alertname": "KubePodCrashLooping"},
                }
            ]
        },
    }
    with patch("requests.get", return_value=mock_resp):
        res = run_scenario.check_alerts(["KubePodCrashLooping"], [])
        assert res is False


def test_check_alerts_request_exception(run_scenario):
    with patch("requests.get", side_effect=Exception("Connection refused")):
        res = run_scenario.check_alerts(["KubePodCrashLooping"], [])
        assert res is False


def test_main_missing_args(run_scenario, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run-scenario.py"])
    with pytest.raises(SystemExit) as exc_info:
        run_scenario.main()
    assert exc_info.value.code == 1


def test_main_missing_label_file(run_scenario, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["run-scenario.py", "nonexistent-scenario"])
    with pytest.raises(SystemExit) as exc_info:
        run_scenario.main()
    assert exc_info.value.code == 1


def test_main_invalid_label_schema(run_scenario, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    labels_dir = tmp_path / "scenarios" / "labels"
    labels_dir.mkdir(parents=True)
    with open(labels_dir / "bad-schema.yaml", "w") as f:
        yaml.dump({"scenario_id": "bad-schema"}, f)

    monkeypatch.setattr(sys, "argv", ["run-scenario.py", "bad-schema"])
    with pytest.raises(SystemExit) as exc_info:
        run_scenario.main()
    assert exc_info.value.code == 1


def test_main_full_workflow_success(run_scenario, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    labels_dir = tmp_path / "scenarios" / "labels"
    labels_dir.mkdir(parents=True)

    scenario_data = {
        "scenario_id": "test-scenario",
        "category": "infra",
        "manifests": ["scenarios/manifests/test-manifest.yaml"],
        "root_cause": {
            "component": "test",
            "failure_mode": "crash",
        },
        "expected_severity": "critical",
        "expected_alerts": ["TestAlert"],
        "red_herring_signals": ["HerringAlert"],
        "valid_remediations": ["fix it"],
        "duration_seconds": 1,
    }
    with open(labels_dir / "test-scenario.yaml", "w") as f:
        yaml.dump(scenario_data, f)

    commands_run = []

    def mock_run_cmd(cmd):
        commands_run.append(cmd)
        return True

    monkeypatch.setattr(run_scenario, "run_cmd", mock_run_cmd)
    monkeypatch.setattr(run_scenario, "check_alerts", lambda exp, red: True)
    monkeypatch.setattr(run_scenario.time, "sleep", lambda sec: None)
    monkeypatch.setattr(sys, "argv", ["run-scenario.py", "test-scenario"])

    with pytest.raises(SystemExit) as exc_info:
        run_scenario.main()
    assert exc_info.value.code == 0

    assert ["kubectl", "apply", "-f", "scenarios/manifests/test-manifest.yaml"] in commands_run
    assert ["kubectl", "delete", "-f", "scenarios/manifests/test-manifest.yaml", "--ignore-not-found"] in commands_run


def test_main_manifest_apply_failure(run_scenario, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    labels_dir = tmp_path / "scenarios" / "labels"
    labels_dir.mkdir(parents=True)

    scenario_data = {
        "scenario_id": "test-scenario",
        "category": "infra",
        "manifests": [
            "scenarios/manifests/test-manifest-1.yaml",
            "scenarios/manifests/test-manifest-2.yaml",
        ],
        "root_cause": {
            "component": "test",
            "failure_mode": "crash",
        },
        "expected_severity": "critical",
        "expected_alerts": ["TestAlert"],
        "red_herring_signals": [],
        "valid_remediations": ["fix it"],
        "duration_seconds": 1,
    }
    with open(labels_dir / "test-scenario.yaml", "w") as f:
        yaml.dump(scenario_data, f)

    commands_run = []

    def mock_run_cmd(cmd):
        commands_run.append(cmd)
        # First manifest apply succeeds, second manifest apply fails
        if cmd == ["kubectl", "apply", "-f", "scenarios/manifests/test-manifest-1.yaml"]:
            return True
        return False

    monkeypatch.setattr(run_scenario, "run_cmd", mock_run_cmd)
    monkeypatch.setattr(sys, "argv", ["run-scenario.py", "test-scenario"])

    with pytest.raises(SystemExit) as exc_info:
        run_scenario.main()
    assert exc_info.value.code == 1

    assert ["kubectl", "apply", "-f", "scenarios/manifests/test-manifest-1.yaml"] in commands_run
    assert ["kubectl", "apply", "-f", "scenarios/manifests/test-manifest-2.yaml"] in commands_run
    # Should clean up the already applied manifest (manifest-1)
    assert ["kubectl", "delete", "-f", "scenarios/manifests/test-manifest-1.yaml", "--ignore-not-found"] in commands_run
    # Should NOT attempt to delete the manifest that failed to apply (manifest-2)
    assert ["kubectl", "delete", "-f", "scenarios/manifests/test-manifest-2.yaml", "--ignore-not-found"] not in commands_run


def test_main_validation_failure_cleans_up(run_scenario, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    labels_dir = tmp_path / "scenarios" / "labels"
    labels_dir.mkdir(parents=True)

    scenario_data = {
        "scenario_id": "test-scenario",
        "category": "infra",
        "manifests": ["scenarios/manifests/test-manifest.yaml"],
        "root_cause": {
            "component": "test",
            "failure_mode": "crash",
        },
        "expected_severity": "critical",
        "expected_alerts": ["TestAlert"],
        "red_herring_signals": [],
        "valid_remediations": ["fix it"],
        "duration_seconds": 1,
    }
    with open(labels_dir / "test-scenario.yaml", "w") as f:
        yaml.dump(scenario_data, f)

    commands_run = []

    def mock_run_cmd(cmd):
        commands_run.append(cmd)
        return True

    monkeypatch.setattr(run_scenario, "run_cmd", mock_run_cmd)
    monkeypatch.setattr(run_scenario, "check_alerts", lambda exp, red: False)
    monkeypatch.setattr(run_scenario.time, "sleep", lambda sec: None)
    monkeypatch.setattr(sys, "argv", ["run-scenario.py", "test-scenario"])

    with pytest.raises(SystemExit) as exc_info:
        run_scenario.main()
    assert exc_info.value.code == 1

    assert ["kubectl", "apply", "-f", "scenarios/manifests/test-manifest.yaml"] in commands_run
    assert ["kubectl", "delete", "-f", "scenarios/manifests/test-manifest.yaml", "--ignore-not-found"] in commands_run
