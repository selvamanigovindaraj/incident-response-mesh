# Scenario Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Golden Dataset catalog with 15 failure scenarios, a Pydantic schema validation pipeline, a Github Actions workflow, and a Python test orchestrator.

**Architecture:** Python `pydantic` handles schema enforcement for the 15 label YAML files. `scripts/run-scenario.py` loads these labels, applies the `manifests`, waits for the duration, polls the Prometheus HTTP API, asserts the expected alerts, and cleans up.

**Tech Stack:** Python 3, Pydantic, PyYAML, Requests, Chaos Mesh, Kubernetes.

**Spec:** `docs/superpowers/specs/2026-09-02-scenario-catalog-design.md`

## Global Constraints

- Pydantic models must use strict types.
- Scenarios must pass `validate.py` script.
- Scenarios must be executed via `make scenario RUN=<id>`.
- The 15 scenarios must follow the exact breakdown specified in the design doc.

---

### Task 1: Ground Truth Schema & Validation Script

**Files:**
- Create: `scenarios/schema.py`
- Create: `scenarios/validate.py`

**Interfaces:**
- Produces: Pydantic classes `ScenarioLabel`, `RootCause` and a script to validate all YAMLs in `scenarios/labels/`.

- [ ] **Step 1: Write `scenarios/schema.py`**

```python
from pydantic import BaseModel
from typing import List, Literal, Optional

class RootCause(BaseModel):
    component: str
    failure_mode: str

class ScenarioLabel(BaseModel):
    scenario_id: str
    category: Literal["infra", "network", "app", "compound"]
    manifests: List[str]
    root_cause: RootCause
    expected_severity: Literal["critical", "warning"]
    expected_alerts: List[str]
    red_herring_signals: List[str]
    valid_remediations: List[str]
    duration_seconds: int
    notes: Optional[str] = None
```

- [ ] **Step 2: Write `scenarios/validate.py`**

```python
import os
import yaml
import sys
from schema import ScenarioLabel

def main():
    labels_dir = "scenarios/labels"
    if not os.path.exists(labels_dir):
        print(f"Directory {labels_dir} does not exist.")
        sys.exit(1)
        
    failed = False
    for filename in os.listdir(labels_dir):
        if not filename.endswith(".yaml"):
            continue
            
        filepath = os.path.join(labels_dir, filename)
        try:
            with open(filepath, 'r') as f:
                data = yaml.safe_load(f)
            ScenarioLabel(**data)
            print(f"✅ {filename} passed validation.")
        except Exception as e:
            print(f"❌ {filename} failed validation:\\n{e}")
            failed = True
            
    if failed:
        sys.exit(1)
    else:
        print("All labels passed schema validation.")

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Commit**

```bash
git add scenarios/schema.py scenarios/validate.py
git commit -m "feat: add pydantic schema and validation script"
```

---

### Task 2: GitHub Actions CI

**Files:**
- Create: `.github/workflows/validate-scenarios.yml`

- [ ] **Step 1: Create CI Workflow**

```yaml
name: Validate Scenario Labels
on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: pip install pydantic pyyaml
      - name: Validate Schema
        run: python scenarios/validate.py
```

- [ ] **Step 2: Commit**

```bash
mkdir -p .github/workflows
git add .github/workflows/validate-scenarios.yml
git commit -m "ci: add github action for scenario validation"
```

---

### Task 3: The Python Orchestrator

**Files:**
- Create: `scripts/run-scenario.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `scenarios/schema.py`
- Produces: CLI execution `python scripts/run-scenario.py <id>`

- [ ] **Step 1: Write `scripts/run-scenario.py`**

```python
import sys
import yaml
import time
import subprocess
import requests

def run_cmd(cmd):
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
    return result.returncode == 0

def check_alerts(expected, red_herrings):
    try:
        resp = requests.get("http://localhost:9090/api/v1/alerts", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        firing_alerts = [alert["labels"]["alertname"] for alert in data["data"] if alert["state"] == "firing"]
        
        all_required = expected + red_herrings
        missing = [a for a in all_required if a not in firing_alerts]
        
        if missing:
            print(f"Missing alerts: {missing}. Currently firing: {firing_alerts}")
            return False
            
        print("All expected and red-herring alerts are actively firing!")
        return True
    except Exception as e:
        print(f"Failed to query Prometheus API: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/run-scenario.py <scenario_id>")
        sys.exit(1)
        
    scenario_id = sys.argv[1]
    label_path = f"scenarios/labels/{scenario_id}.yaml"
    
    with open(label_path, 'r') as f:
        data = yaml.safe_load(f)
        
    manifests = data.get("manifests", [])
    duration = data.get("duration_seconds", 60)
    expected_alerts = data.get("expected_alerts", [])
    red_herrings = data.get("red_herring_signals", [])
    
    print(f"=== Starting Scenario {scenario_id} ===")
    
    # Apply
    for m in manifests:
        if not run_cmd(f"kubectl apply -f {m}"):
            print("Failed to apply manifest. Aborting.")
            sys.exit(1)
            
    print(f"Waiting {duration} seconds for alerts to fire...")
    time.sleep(duration)
    
    # Verify
    success = check_alerts(expected_alerts, red_herrings)
    
    # Cleanup
    print("=== Cleaning up ===")
    for m in manifests:
        run_cmd(f"kubectl delete -f {m} --ignore-not-found")
        
    if success:
        print("✅ Scenario executed and validated successfully.")
        sys.exit(0)
    else:
        print("❌ Scenario validation failed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add Make target**

Append to `Makefile`:
```makefile

.PHONY: scenario
scenario:
	@if [ -z "$(RUN)" ]; then echo "Usage: make scenario RUN=<id>"; exit 1; fi
	pip install pydantic pyyaml requests > /dev/null 2>&1 || true
	python3 scripts/run-scenario.py $(RUN)
```

- [ ] **Step 3: Commit**

```bash
git add scripts/run-scenario.py Makefile
git commit -m "feat: add python scenario orchestrator"
```

---

### Task 4: Infra Scenarios

**Files:**
- Create: `scenarios/manifests/infra-pod-oom.yaml` and label
- Create: `scenarios/manifests/infra-node-cpu.yaml` and label
- Create: `scenarios/manifests/infra-pvc-full.yaml` and label
- Create: `scenarios/manifests/infra-pod-eviction.yaml` and label

- [ ] **Step 1: Write `infra-pod-oom`**
Create `scenarios/labels/infra-pod-oom.yaml`:
```yaml
scenario_id: infra-pod-oom
category: infra
manifests:
  - scenarios/manifests/infra-pod-oom.yaml
root_cause:
  component: kafka
  failure_mode: oom_kill
expected_severity: critical
expected_alerts:
  - KubePodCrashLooping
red_herring_signals: []
valid_remediations:
  - Increase memory limit for kafka statefulset
duration_seconds: 60
```
Create `scenarios/manifests/infra-pod-oom.yaml`:
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: kafka-oom
  namespace: victim
spec:
  mode: one
  selector:
    labelSelectors:
      app.kubernetes.io/name: kafka
  stressors:
    memory:
      workers: 4
      size: '1GB'
  duration: '90s'
```

- [ ] **Step 2: Write `infra-node-cpu`**
Create `scenarios/labels/infra-node-cpu.yaml`:
```yaml
scenario_id: infra-node-cpu
category: infra
manifests:
  - scenarios/manifests/infra-node-cpu.yaml
root_cause:
  component: agent-node
  failure_mode: cpu_starvation
expected_severity: warning
expected_alerts:
  - NodeHighCpuLoad
red_herring_signals: []
valid_remediations:
  - Provision additional nodes
  - Identify and kill rogue CPU processes
duration_seconds: 60
```
Create `scenarios/manifests/infra-node-cpu.yaml`:
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: node-cpu
  namespace: victim
spec:
  mode: all
  selector:
    labelSelectors:
      app.kubernetes.io/name: frontend
  stressors:
    cpu:
      workers: 4
      load: 100
  duration: '90s'
```

- [ ] **Step 3: Write `infra-pvc-full`**
Create `scenarios/labels/infra-pvc-full.yaml`:
```yaml
scenario_id: infra-pvc-full
category: infra
manifests: []
root_cause:
  component: opensearch
  failure_mode: disk_full
expected_severity: critical
expected_alerts:
  - KubePersistentVolumeFillingUp
red_herring_signals: []
valid_remediations:
  - Expand PVC storage size
duration_seconds: 60
```

- [ ] **Step 4: Write `infra-pod-eviction`**
Create `scenarios/labels/infra-pod-eviction.yaml`:
```yaml
scenario_id: infra-pod-eviction
category: infra
manifests:
  - scenarios/manifests/infra-pod-eviction.yaml
root_cause:
  component: checkout
  failure_mode: eviction
expected_severity: warning
expected_alerts:
  - KubePodNotReady
red_herring_signals: []
valid_remediations:
  - Increase ephemeral storage limits
duration_seconds: 60
```
Create `scenarios/manifests/infra-pod-eviction.yaml`:
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: checkout-evict
  namespace: victim
spec:
  action: pod-kill
  mode: one
  selector:
    labelSelectors:
      app.kubernetes.io/name: checkout
  duration: '90s'
```

- [ ] **Step 5: Commit**
```bash
git add scenarios/labels/infra* scenarios/manifests/infra*
git commit -m "feat: add infrastructure scenarios"
```

---

### Task 5: Network Scenarios

- [ ] **Step 1: Write `network-db-partition`**
Create `scenarios/labels/network-db-partition.yaml`:
```yaml
scenario_id: network-db-partition
category: network
manifests:
  - scenarios/manifests/network-db-partition.yaml
root_cause:
  component: valkey-cart
  failure_mode: network_partition
expected_severity: critical
expected_alerts:
  - CartServiceHighErrorRate
red_herring_signals: []
valid_remediations:
  - Restore network connectivity between cart and valkey
duration_seconds: 60
```
Create `scenarios/manifests/network-db-partition.yaml`:
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: valkey-partition
  namespace: victim
spec:
  action: partition
  mode: all
  selector:
    labelSelectors:
      app.kubernetes.io/name: valkey-cart
  direction: both
  duration: '90s'
```

- [ ] **Step 2: Write `network-api-latency`**
Create `scenarios/labels/network-api-latency.yaml`:
```yaml
scenario_id: network-api-latency
category: network
manifests:
  - scenarios/manifests/network-api-latency.yaml
root_cause:
  component: checkout
  failure_mode: high_latency
expected_severity: warning
expected_alerts:
  - CheckoutServiceHighLatency
red_herring_signals: []
valid_remediations:
  - Investigate checkout service performance
duration_seconds: 60
```
Create `scenarios/manifests/network-api-latency.yaml`:
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: checkout-latency
  namespace: victim
spec:
  action: delay
  mode: all
  selector:
    labelSelectors:
      app.kubernetes.io/name: checkout
  delay:
    latency: '500ms'
  duration: '90s'
```

- [ ] **Step 3: Write `network-dns-failure`**
Create `scenarios/labels/network-dns-failure.yaml`:
```yaml
scenario_id: network-dns-failure
category: network
manifests:
  - scenarios/manifests/network-dns-failure.yaml
root_cause:
  component: coredns
  failure_mode: dns_resolution_failure
expected_severity: critical
expected_alerts:
  - DNSResolutionFailing
red_herring_signals: []
valid_remediations:
  - Restart coredns pods
duration_seconds: 60
```
Create `scenarios/manifests/network-dns-failure.yaml`:
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: DNSChaos
metadata:
  name: dns-fail
  namespace: victim
spec:
  action: error
  mode: all
  selector:
    labelSelectors:
      app.kubernetes.io/name: frontend
  patterns:
    - '*'
  duration: '90s'
```

- [ ] **Step 4: Write `network-packet-loss`**
Create `scenarios/labels/network-packet-loss.yaml`:
```yaml
scenario_id: network-packet-loss
category: network
manifests:
  - scenarios/manifests/network-packet-loss.yaml
root_cause:
  component: payment
  failure_mode: packet_loss
expected_severity: warning
expected_alerts:
  - PaymentServiceHighErrorRate
red_herring_signals: []
valid_remediations:
  - Investigate network interface on payment node
duration_seconds: 60
```
Create `scenarios/manifests/network-packet-loss.yaml`:
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: payment-loss
  namespace: victim
spec:
  action: loss
  mode: all
  selector:
    labelSelectors:
      app.kubernetes.io/name: payment
  loss:
    loss: '20'
  duration: '90s'
```

- [ ] **Step 5: Commit**
```bash
git add scenarios/labels/network* scenarios/manifests/network*
git commit -m "feat: add network scenarios"
```

---

### Task 6: App-Level Scenarios

*Because flagd manifests require patching configmaps dynamically, we will use basic PodChaos as placeholders for the app scenarios to maintain the schema, replacing them later when flagd targets are explicitly mapped in Phase 1.*

- [ ] **Step 1: Write `app-cache-failure`**
Create `scenarios/labels/app-cache-failure.yaml`:
```yaml
scenario_id: app-cache-failure
category: app
manifests: []
root_cause:
  component: recommendation
  failure_mode: cache_disabled
expected_severity: warning
expected_alerts:
  - RecommendationHighLatency
red_herring_signals: []
valid_remediations:
  - Re-enable cache feature flag
duration_seconds: 60
```

- [ ] **Step 2: Write `app-slow-dependency`**
Create `scenarios/labels/app-slow-dependency.yaml`:
```yaml
scenario_id: app-slow-dependency
category: app
manifests: []
root_cause:
  component: shipping
  failure_mode: slow_third_party
expected_severity: warning
expected_alerts:
  - ShippingHighLatency
red_herring_signals: []
valid_remediations:
  - Disable third party integration flag
duration_seconds: 60
```

- [ ] **Step 3: Write `app-error-spike`**
Create `scenarios/labels/app-error-spike.yaml`:
```yaml
scenario_id: app-error-spike
category: app
manifests: []
root_cause:
  component: checkout
  failure_mode: forced_errors
expected_severity: critical
expected_alerts:
  - CheckoutErrorSpike
red_herring_signals: []
valid_remediations:
  - Rollback faulty feature flag
duration_seconds: 60
```

- [ ] **Step 4: Write `app-invalid-config`**
Create `scenarios/labels/app-invalid-config.yaml`:
```yaml
scenario_id: app-invalid-config
category: app
manifests: []
root_cause:
  component: product-catalog
  failure_mode: malformed_json
expected_severity: warning
expected_alerts:
  - CatalogServiceCrash
red_herring_signals: []
valid_remediations:
  - Revert configuration change
duration_seconds: 60
```

- [ ] **Step 5: Write `app-feature-crash`**
Create `scenarios/labels/app-feature-crash.yaml`:
```yaml
scenario_id: app-feature-crash
category: app
manifests: []
root_cause:
  component: frontend
  failure_mode: unhandled_exception
expected_severity: critical
expected_alerts:
  - FrontendServiceDown
red_herring_signals: []
valid_remediations:
  - Disable new feature flag immediately
duration_seconds: 60
```

- [ ] **Step 6: Commit**
```bash
git add scenarios/labels/app*
git commit -m "feat: add app-level scenario labels"
```

---

### Task 7: Compound Scenarios

- [ ] **Step 1: Write `compound-latency-retry`**
Create `scenarios/labels/compound-latency-retry.yaml`:
```yaml
scenario_id: compound-latency-retry
category: compound
manifests:
  - scenarios/manifests/network-api-latency.yaml
root_cause:
  component: network-and-flag
  failure_mode: latency_with_retry_storm
expected_severity: critical
expected_alerts:
  - CheckoutHighLatency
red_herring_signals:
  - ApiGatewayTimeout
valid_remediations:
  - "1. Disable retry feature flag"
  - "2. Remove network latency injection"
duration_seconds: 60
```

- [ ] **Step 2: Write `compound-node-cache`**
Create `scenarios/labels/compound-node-cache.yaml`:
```yaml
scenario_id: compound-node-cache
category: compound
manifests:
  - scenarios/manifests/infra-node-cpu.yaml
root_cause:
  component: node-and-flag
  failure_mode: cpu_starvation_and_cache_miss
expected_severity: warning
expected_alerts:
  - NodeHighCpuLoad
red_herring_signals:
  - FrontendHigh5xxRates
valid_remediations:
  - "1. Enable fallback cache flag"
  - "2. Provision new node or kill stressor"
duration_seconds: 60
```

- [ ] **Step 3: Commit**
```bash
git add scenarios/labels/compound*
git commit -m "feat: add compound scenario labels"
```
