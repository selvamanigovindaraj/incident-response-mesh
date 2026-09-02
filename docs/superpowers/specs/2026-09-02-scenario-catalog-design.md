# Scenario Catalog & Golden Dataset Design

## 1. Context & Goals
Phase 9 of the Incident Response Mesh project requires a highly structured, machine-readable "golden dataset" to evaluate AI diagnostic performance. Because we inject the failures using Chaos Mesh and `flagd`, we know the absolute ground truth. 

This spec defines a 15-scenario catalog spanning infra, network, app, and compound failures. Each scenario pairs an executable chaos manifest with a strict Pydantic-validated ground truth label.

## 2. Directory Structure
```text
scenarios/
├── schema.py                   # Pydantic models for CI validation
├── validate.py                 # Script invoked by CI to check all labels
├── labels/
│   ├── infra-pod-oom.yaml
│   ├── ... (15 YAML label files)
└── manifests/
    ├── infra-pod-oom-chaos.yaml
    ├── app-cache-error-flag.yaml
    ├── ... (Chaos/Flagd injection manifests)
scripts/
└── run-scenario.py             # The Python execution harness
.github/
└── workflows/
    └── validate-scenarios.yml  # CI Schema validation
```

## 3. Ground-Truth Schema (`scenarios/schema.py`)
```python
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
    valid_remediations: List[str]  # Ordered from step 1 to N
    duration_seconds: int
    notes: Optional[str]
```

## 4. The Orchestrator (`scripts/run-scenario.py`)
Integrated into the Makefile as `make scenario RUN=<id>`.
1. Loads `scenarios/labels/<id>.yaml` using Pydantic.
2. Applies all files listed in `manifests` via `subprocess.run(["kubectl", "apply", "-f", ...])`.
3. Sleeps for `duration_seconds`.
4. Polls `http://localhost:9090/api/v1/alerts` (or via k8s port-forwarding if run externally).
5. Asserts that `expected_alerts` and `red_herring_signals` are present in the JSON response payload.
6. Runs `kubectl delete -f` on the manifests to clean up.
7. Exits 0 if all assertions pass, 1 otherwise.

## 5. The 15-Scenario Distribution
Total: 6 Critical, 9 Warning. 

### Infra Scenarios
1. **infra-pod-oom** (Critical): Kafka container OOMKill.
2. **infra-node-cpu** (Warning): High CPU load on agent node.
3. **infra-pvc-full** (Critical): Prometheus storage fills up.
4. **infra-pod-eviction** (Warning): Node disk pressure causes eviction.

### Network Scenarios
5. **network-db-partition** (Critical): Cart service cannot reach Valkey.
6. **network-api-latency** (Warning): 500ms delay between frontend and checkout.
7. **network-dns-failure** (Critical): CoreDNS drops traffic.
8. **network-packet-loss** (Warning): 20% loss on payment service.

### App-Level Scenarios (via flagd)
9. **app-cache-failure** (Warning): Feature flag disables cache in recommendation service.
10. **app-slow-dependency** (Warning): Flag injects sleep() in shipping service.
11. **app-error-spike** (Critical): Flag forces 500 errors in checkout service.
12. **app-invalid-config** (Warning): Flag pushes malformed JSON to product catalog.
13. **app-feature-crash** (Critical): Bad feature flag completely crashes frontend process.

### Compound Scenarios
14. **compound-latency-retry** (Critical)
    * **Root Cause:** Network Latency (Chaos) + Aggressive Retry Loop (flagd).
    * **Red Herring:** API Gateway Timeout (Symptom, not the cause).
    * **Remediations:** `["1. Disable retry feature flag", "2. Remove network latency injection"]`.
15. **compound-node-cache** (Warning)
    * **Root Cause:** Node CPU Starvation (Chaos) + Cache Disabled (flagd).
    * **Red Herring:** High 5xx Rates.
    * **Remediations:** `["1. Enable fallback cache flag", "2. Provision new node / kill stressor"]`.

## 6. GitHub Actions CI
A workflow triggers on `pull_request` and `push` to `main`. It runs `pip install pydantic pyyaml` and executes `scenarios/validate.py` to ensure schema integrity across all 15 golden labels.
