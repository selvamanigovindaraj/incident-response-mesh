# Chaos Mesh Implementation Plan

This plan implements the Chaos Mesh controller and the five foundational failure injection experiments.

## Dependencies
- k3d cluster must be running (`make cluster-up`)
- The victim app should be deployable (`make victim-up`) to test the actual experiments.

---

### Task 1: Create Chaos Mesh Helm Values
Create the Helm values to securely deploy Chaos Mesh. We must enforce RBAC by locking the controller to the `victim` namespace and disable unneeded components.

**Files:**
- Create: `infra/chaos/values-local.yaml`

**Interfaces:**
- Produces: Base Helm configuration for Chaos Mesh.

- [ ] **Step 1: Write `infra/chaos/values-local.yaml`**
```yaml
chaosDaemon:
  # k3d runs on containerd, not docker
  runtime: containerd
  socketPath: /run/k3s/containerd/containerd.sock

controllerManager:
  # CRITICAL: Restrict Chaos Mesh to ONLY affect the victim namespace
  targetNamespace: victim

dashboard:
  create: true
  # We will access this via port-forward, no ingress needed
  ingress:
    enabled: false
```

- [ ] **Step 2: Verify YAML**
Run `cat infra/chaos/values-local.yaml` to ensure syntax is valid.

- [ ] **Step 3: Commit**
```bash
mkdir -p infra/chaos
git add infra/chaos/values-local.yaml
git commit -m "infra: add base helm values for chaos mesh"
```

---

### Task 2: Add Chaos Makefile Targets
Add `chaos-up`, `chaos-down`, `chaos-dashboard`, and the `chaos` wrapper to the Makefile.

**Files:**
- Modify: `Makefile`

**Interfaces:**
- Produces: Makefile commands to spin the control plane up and down, and run experiments.

- [ ] **Step 1: Append to `Makefile`**
Ensure REAL TABS are used for indentation. Append this to the bottom of the file.

```makefile

.PHONY: chaos-up
chaos-up: check-prereqs
	helm repo add chaos-mesh https://charts.chaos-mesh.org
	helm repo update chaos-mesh
	helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh --version 2.7.0 \
		--namespace chaos --create-namespace \
		-f infra/chaos/values-local.yaml
	@echo "Waiting for Chaos Mesh to be Ready..."
	kubectl wait --for=condition=ready pod -l app.kubernetes.io/instance=chaos-mesh -n chaos --timeout=5m

.PHONY: chaos-down
chaos-down: check-prereqs
	helm uninstall chaos-mesh -n chaos || true
	kubectl delete namespace chaos --ignore-not-found

.PHONY: chaos-dashboard
chaos-dashboard: check-prereqs
	@echo "Access the dashboard at http://localhost:2333"
	kubectl port-forward -n chaos svc/chaos-dashboard 2333:2333

.PHONY: chaos
chaos: check-prereqs
	@if [ -z "$(RUN)" ]; then echo "Error: Must specify experiment (e.g., make chaos RUN=pod-kill)"; exit 1; fi
	./scripts/run-chaos.sh $(RUN)
```

- [ ] **Step 2: Commit**
```bash
git add Makefile
git commit -m "infra: add make targets for chaos mesh and experiments"
```

---

### Task 3: Write the Runner Script
Create the `run-chaos.sh` bash script which strictly applies, waits, and purges experiments.

**Files:**
- Create: `scripts/run-chaos.sh`

**Interfaces:**
- Consumes: The `RUN` argument (e.g. `pod-kill`).
- Produces: An executable bash script.

- [ ] **Step 1: Write `scripts/run-chaos.sh`**
```bash
#!/usr/bin/env bash
set -eo pipefail

if [ -z "$1" ]; then
  echo "Usage: $0 <experiment-name>"
  exit 1
fi

EXP_FILE="chaos/experiments/$1.yaml"
if [ ! -f "$EXP_FILE" ]; then
  echo "❌ Error: Experiment file $EXP_FILE not found."
  exit 1
fi

# Extract duration string (e.g., '60s', '1m') using grep/awk
DURATION_STR=$(grep -E "^  duration: " "$EXP_FILE" | awk '{print $2}' | tr -d '"'\''')
if [ -z "$DURATION_STR" ]; then
  echo "❌ Error: Could not parse 'duration' from $EXP_FILE"
  exit 1
fi

# Very naive parsing for s or m
if [[ $DURATION_STR == *m ]]; then
  WAIT_TIME=$(( ${DURATION_STR%m} * 60 ))
elif [[ $DURATION_STR == *s ]]; then
  WAIT_TIME=${DURATION_STR%s}
else
  WAIT_TIME=$DURATION_STR
fi

echo "==> 🌪️ Starting Chaos Experiment: $1"
kubectl apply -f "$EXP_FILE"

echo "⏳ Waiting for ${WAIT_TIME} seconds..."
sleep "$WAIT_TIME"

echo "==> 🧹 Cleaning up Chaos Experiment: $1"
kubectl delete -f "$EXP_FILE"
echo "✅ Experiment complete and purged."
```

- [ ] **Step 2: Make executable and commit**
```bash
chmod +x scripts/run-chaos.sh
git add scripts/run-chaos.sh
git commit -m "test: add strict runner script for chaos experiments"
```

---

### Task 4: Foundation Experiments (Network & Pod)
Codify the first three chaos experiments for pod failure and network degradation.

**Files:**
- Create: `chaos/experiments/pod-kill.yaml`
- Create: `chaos/experiments/network-delay.yaml`
- Create: `chaos/experiments/network-partition.yaml`

- [ ] **Step 1: Create `chaos/experiments/pod-kill.yaml`**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: frontend-proxy-kill
  namespace: victim
spec:
  action: pod-kill
  mode: one
  duration: "60s"
  selector:
    namespaces:
      - victim
    labelSelectors:
      app.kubernetes.io/name: frontend-proxy
```

- [ ] **Step 2: Create `chaos/experiments/network-delay.yaml`**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: recommendation-delay
  namespace: victim
spec:
  action: delay
  mode: all
  selector:
    namespaces:
      - victim
    labelSelectors:
      app.kubernetes.io/name: recommendation
  delay:
    latency: "300ms"
  duration: "60s"
```

- [ ] **Step 3: Create `chaos/experiments/network-partition.yaml`**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: frontend-cart-partition
  namespace: victim
spec:
  action: partition
  mode: all
  selector:
    namespaces:
      - victim
    labelSelectors:
      app.kubernetes.io/name: frontend
  direction: both
  target:
    selector:
      namespaces:
        - victim
      labelSelectors:
        app.kubernetes.io/name: cart
    mode: all
  duration: "60s"
```

- [ ] **Step 4: Commit**
```bash
mkdir -p chaos/experiments
git add chaos/experiments
git commit -m "test: codify pod-kill and network chaos experiments"
```

---

### Task 5: Foundation Experiments (Stress & DNS)
Codify the final two chaos experiments for resource exhaustion and DNS spoofing.

**Files:**
- Create: `chaos/experiments/cpu-stress.yaml`
- Create: `chaos/experiments/dns-failure.yaml`

- [ ] **Step 1: Create `chaos/experiments/cpu-stress.yaml`**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: load-generator-cpu-stress
  namespace: victim
spec:
  mode: all
  selector:
    namespaces:
      - victim
    labelSelectors:
      app.kubernetes.io/name: load-generator
  stressors:
    cpu:
      workers: 1
      load: 100
  duration: "60s"
```

- [ ] **Step 2: Create `chaos/experiments/dns-failure.yaml`**
```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: DNSChaos
metadata:
  name: payment-dns-error
  namespace: victim
spec:
  action: error
  mode: all
  selector:
    namespaces:
      - victim
    labelSelectors:
      app.kubernetes.io/name: payment
  patterns:
    - "*"
  duration: "60s"
```

- [ ] **Step 3: Commit**
```bash
git add chaos/experiments
git commit -m "test: codify cpu-stress and dns-failure chaos experiments"
```
