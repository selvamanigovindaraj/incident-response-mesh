import os
import sys

_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
_scenarios_dir = os.path.join(_repo_root, "scenarios")
if _scenarios_dir not in sys.path:
    sys.path.insert(0, _scenarios_dir)

import subprocess
import time

import requests
import yaml

try:
    from schema import ScenarioLabel
except ImportError:
    from scenarios.schema import ScenarioLabel


def run_cmd(cmd):
    if isinstance(cmd, list):
        print(f"Running: {' '.join(cmd)}")
    else:
        print(f"Running: {cmd}")
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
    return result.returncode == 0


def check_alerts(expected, red_herrings):
    try:
        resp = requests.get("http://localhost:9090/api/v1/alerts", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        raw_data = data.get("data", [])
        if isinstance(raw_data, dict):
            alerts_list = raw_data.get("alerts", [])
        elif isinstance(raw_data, list):
            alerts_list = raw_data
        else:
            alerts_list = []

        firing_alerts = [
            alert["labels"]["alertname"]
            for alert in alerts_list
            if (alert.get("state") == "firing" or alert.get("status") == "firing")
            and isinstance(alert.get("labels"), dict)
            and "alertname" in alert["labels"]
        ]

        all_required = expected + red_herrings
        missing = [a for a in all_required if a not in firing_alerts]

        if missing:
            print(f"Missing alerts: {missing}. Currently firing: {firing_alerts}")
            return False

        print("All expected and red-herring alerts are actively firing!")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"Failed to query Prometheus API: {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/run-scenario.py <scenario_id>")
        sys.exit(1)

    scenario_id = sys.argv[1]
    label_path = f"scenarios/labels/{scenario_id}.yaml"
    if not os.path.exists(label_path):
        if os.path.exists(f"labels/{scenario_id}.yaml"):
            label_path = f"labels/{scenario_id}.yaml"
        else:
            print(f"Error: Scenario label file not found at {label_path}")
            sys.exit(1)

    with open(label_path, "r") as f:
        data = yaml.safe_load(f)

    try:
        scenario = ScenarioLabel(**data)
        manifests = scenario.manifests
        duration = scenario.duration_seconds
        expected_alerts = scenario.expected_alerts
        red_herrings = scenario.red_herring_signals
    except Exception as e:  # noqa: BLE001
        print(f"Validation error for scenario {scenario_id}: {e}")
        sys.exit(1)

    print(f"=== Starting Scenario {scenario_id} ===")

    # Apply
    applied_manifests = []
    for m in manifests:
        if not run_cmd(["kubectl", "apply", "-f", m]):
            print("Failed to apply manifest. Aborting.")
            for applied in applied_manifests:
                run_cmd(["kubectl", "delete", "-f", applied, "--ignore-not-found"])
            sys.exit(1)
        applied_manifests.append(m)

    print(f"Waiting {duration} seconds for alerts to fire...")
    time.sleep(duration)

    # Verify
    success = check_alerts(expected_alerts, red_herrings)

    # Cleanup
    print("=== Cleaning up ===")
    for m in manifests:
        run_cmd(["kubectl", "delete", "-f", m, "--ignore-not-found"])

    if success:
        print("✅ Scenario executed and validated successfully.")
        sys.exit(0)
    else:
        print("❌ Scenario validation failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
