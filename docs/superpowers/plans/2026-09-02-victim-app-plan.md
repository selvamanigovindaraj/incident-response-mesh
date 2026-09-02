# Victim App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the OpenTelemetry Astronomy Shop Demo into the local cluster as the "victim" application with tightly constrained resources and automated smoke tests.

**Architecture:** We use Helm to deploy the `opentelemetry-demo` chart (v0.41.0) into the `victim` namespace. Resources are constrained via `infra/victim/values-local.yaml`. A bash script verifies health and telemetry via `curl` and `jq`.

**Tech Stack:** Makefile, Helm, bash, curl, jq, kubectl.

**Spec:** `docs/superpowers/specs/2026-09-02-victim-app-design.md`

## Global Constraints

- No custom Prometheus/Alertmanager (monitoring stack is out of scope for this spec).
- Total footprint must be <6GB (enforced via strict memory limits).
- All cluster definitions go inside `infra/victim/`.

---

### Task 1: Update Prerequisites in Makefile

**Files:**
- Modify: `Makefile`

**Interfaces:**
- Produces: An updated `check-prereqs` target that also validates `jq` is installed (required for parsing Jaeger JSON).

- [ ] **Step 1: Update `check-prereqs` in `Makefile`**

Modify the `check-prereqs` target in `Makefile` to include a check for `jq`.

```makefile
.PHONY: check-prereqs
check-prereqs:
	@command -v docker >/dev/null 2>&1 || { echo >&2 "docker is required but not installed. Aborting."; exit 1; }
	@command -v k3d >/dev/null 2>&1 || { echo >&2 "k3d is required but not installed. Aborting."; exit 1; }
	@command -v kubectl >/dev/null 2>&1 || { echo >&2 "kubectl is required but not installed. Aborting."; exit 1; }
	@command -v helm >/dev/null 2>&1 || { echo >&2 "helm is required but not installed. Aborting."; exit 1; }
	@command -v jq >/dev/null 2>&1 || { echo >&2 "jq is required but not installed. Aborting."; exit 1; }
	@echo "All prerequisites found."
```

- [ ] **Step 2: Verify `check-prereqs` works**

Run: `make check-prereqs`
Expected: Exits successfully (assuming jq is installed).

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "chore: add jq to prerequisite checks"
```

### Task 2: Create Victim Helm Values Configuration

**Files:**
- Create: `infra/victim/values-local.yaml`

**Interfaces:**
- Produces: `infra/victim/values-local.yaml` to be used by the Helm upgrade command.

- [ ] **Step 1: Write `infra/victim/values-local.yaml`**

```yaml
default:
  resources:
    limits:
      memory: 250Mi
      cpu: 200m
    requests:
      memory: 50Mi
      cpu: 50m

components:
  prometheus:
    enabled: false
  grafana:
    enabled: false
  frontendProxy:
    ingress:
      enabled: true
      ingressClassName: traefik
      hosts:
        - host: localhost
          paths:
            - path: /
              pathType: Prefix
              port: 8080
  featureflagservice:
    ingress:
      enabled: true
      ingressClassName: traefik
      hosts:
        - host: localhost
          paths:
            - path: /feature
              pathType: Prefix
              port: 8081
```

- [ ] **Step 2: Verify YAML**

Run: `cat infra/victim/values-local.yaml`
Expected: Valid YAML output.

- [ ] **Step 3: Commit**

```bash
mkdir -p infra/victim
git add infra/victim/values-local.yaml
git commit -m "infra: add local helm values for victim app"
```

### Task 3: Implement Victim Lifecycle Makefile Targets

**Files:**
- Modify: `Makefile`

**Interfaces:**
- Consumes: `infra/victim/values-local.yaml`.
- Produces: `victim-up` and `victim-down` commands.

- [ ] **Step 1: Add lifecycle targets to Makefile**

Append the following to the `Makefile`:

```makefile

.PHONY: victim-up
victim-up: check-prereqs
	helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
	helm repo update open-telemetry
	helm upgrade --install opentelemetry-demo open-telemetry/opentelemetry-demo --version 0.41.0 \
		--namespace victim --create-namespace \
		-f infra/victim/values-local.yaml
	@echo "Waiting for all pods in victim namespace to be Ready (this may take up to 10 minutes)..."
	kubectl wait --for=condition=ready pod --all -n victim --timeout=10m

.PHONY: victim-down
victim-down: check-prereqs
	helm uninstall opentelemetry-demo -n victim || true
	kubectl delete namespace victim --ignore-not-found
```

- [ ] **Step 2: Dry-run check**

Run: `cat Makefile` to visually verify the commands are present and use real tabs.
*(We won't run `make victim-up` yet as it takes a long time, we'll run it once during the smoke test task).*

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "infra: add make targets for victim up and down"
```

### Task 4: Write Smoke Test Script

**Files:**
- Create: `scripts/smoke-test.sh`

**Interfaces:**
- Produces: An executable bash script that verifies the victim application.

- [ ] **Step 1: Write `scripts/smoke-test.sh`**

```bash
#!/usr/bin/env bash
set -eo pipefail

echo "==> Running Victim Application Smoke Test <=="

echo "1. Checking Frontend Health..."
# Retry up to 5 times to allow Ingress routing to settle
for i in {1..5}; do
  if curl -s --fail http://localhost:8080/ > /dev/null; then
    echo "Frontend is healthy."
    break
  fi
  if [ $i -eq 5 ]; then
    echo "Frontend health check failed."
    exit 1
  fi
  sleep 2
done

echo "2. Checking Telemetry Flow in Jaeger..."
# Port-forward Jaeger query service in the background
kubectl port-forward svc/opentelemetry-demo-jaeger-query 16686:16686 -n victim > /dev/null 2>&1 &
PF_PID=$!

# Ensure we kill the port-forward on script exit
trap "kill $PF_PID 2>/dev/null || true" EXIT

# Wait for port-forward to establish
sleep 3

# Query Jaeger API for traces from the frontend service
TRACES=$(curl -s "http://localhost:16686/api/traces?service=frontend")
TRACE_COUNT=$(echo "$TRACES" | jq '.data | length')

if [ "$TRACE_COUNT" -gt 0 ]; then
  echo "Telemetry verified. Found $TRACE_COUNT traces for frontend."
else
  echo "Telemetry verification failed. No traces found."
  exit 1
fi

echo "3. Checking Failure State..."
kubectl scale deploy/opentelemetry-demo-frontend --replicas=0 -n victim
echo "Waiting for frontend to scale down..."
sleep 10

if curl -s --fail http://localhost:8080/ > /dev/null; then
  echo "Expected frontend to fail, but it succeeded!"
  exit 1
else
  echo "Frontend correctly failed when scaled to 0."
fi

echo "Restoring frontend..."
kubectl scale deploy/opentelemetry-demo-frontend --replicas=1 -n victim
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=frontend -n victim --timeout=2m

echo "==> Smoke Test Passed! <=="
```

- [ ] **Step 2: Make executable**

Run: `chmod +x scripts/smoke-test.sh`

- [ ] **Step 3: Commit**

```bash
mkdir -p scripts
git add scripts/smoke-test.sh
git commit -m "test: add victim smoke test script"
```

### Task 5: Add Smoke Test to Makefile

**Files:**
- Modify: `Makefile`

**Interfaces:**
- Consumes: `scripts/smoke-test.sh`.

- [ ] **Step 1: Add `victim-smoke` target**

Append to `Makefile`:

```makefile

.PHONY: victim-smoke
victim-smoke: check-prereqs
	./scripts/smoke-test.sh
```

- [ ] **Step 2: Test the entire pipeline**

Run: `make cluster-up victim-up victim-smoke`
Expected: The cluster spins up, helm chart deploys (and waits for readiness), and the smoke test executes and passes cleanly.

- [ ] **Step 3: Clean up**

Run: `make cluster-down`
Expected: Cluster is torn down cleanly.

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "test: add victim-smoke target"
```
