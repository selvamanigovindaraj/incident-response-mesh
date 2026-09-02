# Design Specification: Victim Application Deployment

## Overview
This specification details the integration of the OpenTelemetry Astronomy Shop Demo as the "victim" application for the `incident-response-mesh` repository. It provides a pre-instrumented microservices environment that fits within a local developer's laptop constraints (under 6GB RAM), deployed into a local k3d cluster with automated verification.

## Scope
- **In Scope:** Helm-based deployment of the OTel demo into the `victim` namespace, heavily tuned resource configurations (`values-local.yaml`), a bash-based smoke test script, and lifecycle Makefile targets (`victim-up`, `victim-down`, `victim-smoke`).
- **Out of Scope:** Custom Prometheus/Alertmanager stacks, custom instrumentation changes to the demo itself.

## 1. Directory Structure & Components
- **`infra/victim/values-local.yaml`**: Declarative Helm values overriding the default chart. It will:
  - Aggressively throttle `resources.limits.memory` and `CPU` for all microservices.
  - Set replicas to exactly `1` for all components.
  - Enable Ingress routing for the `frontend` and the `feature-flag` services.
- **`scripts/smoke-test.sh`**: Bash script asserting the health and telemetry flow of the deployed application. It will rely on `curl` and `jq`.
- **`Makefile`**: Extended to include the victim deployment lifecycle targets.

## 2. Infrastructure Configuration
We will use the official `opentelemetry-demo` Helm chart. The version must be explicitly pinned in the `Makefile` or deployment scripts to prevent upstream breakages. 

### Networking
Because we enabled Traefik in our foundational k3d setup (which maps host port `8080` to the cluster LoadBalancer), we will expose the demo externally without manual port-forwarding for standard access:
- **Frontend**: `http://localhost:8080/`
- **Feature Flags**: `http://localhost:8080/feature/`

## 3. Makefile Workflows
- **`make victim-up`**:
  - Adds the `open-telemetry` Helm repository.
  - Executes `helm upgrade --install` into the `victim` namespace using `infra/victim/values-local.yaml`.
  - Executes `kubectl wait` to block until all pods in the `victim` namespace achieve a `Ready` state (timeout: 10m).
- **`make victim-down`**:
  - Executes `helm uninstall` and deletes the `victim` namespace to ensure a clean slate.
- **`make victim-smoke`**:
  - Executes `scripts/smoke-test.sh`.

## 4. Smoke Test Assertions
The `scripts/smoke-test.sh` will perform three critical tests:
1. **Health Verification**: `curl -s --fail http://localhost:8080/` (asserts the frontend is alive).
2. **Telemetry Verification**:
   - Spawns a background `kubectl port-forward` to the bundled Jaeger query service on port `16686`.
   - Queries the Jaeger API: `http://localhost:16686/api/traces?service=frontend`.
   - Uses `jq` to parse the JSON and asserts that trace data is present and actively flowing.
   - Cleans up the port-forward process.
3. **Failure State Verification**:
   - Scales the frontend deployment to `0`: `kubectl scale deploy/opentelemetry-demo-frontend --replicas=0 -n victim`.
   - Verifies that `curl` requests now return a failure/non-2xx response.
   - Scales the frontend deployment back to `1` and waits for readiness, leaving the environment clean.

## Acceptance Criteria
- [ ] `make victim-up` results in a fully Ready deployment within 10 minutes.
- [ ] The total memory footprint of the cluster remains under 6GB.
- [ ] The `victim-smoke` target exits `0` on a healthy deploy and validates the scale-to-zero failure state successfully.
- [ ] The Helm chart version is strictly pinned.
