# Monitoring Stack & Alert Generation Design

## Context
To train and test our incident response mesh agents effectively, we need realistic, production-grade alert payloads. This specification details the deployment of the `kube-prometheus-stack` into our local k3d cluster, the configuration of curated alerting rules, and the automated capture of those alerts into fixture files for future use.

## Architecture & Components

### 1. Prometheus Stack (`kube-prometheus-stack`)
We will deploy the official Prometheus community Helm chart into the `monitoring` namespace.
*   **Prometheus**: Scrapes the `victim` namespace to monitor application health. Exposed locally on port `9090`.
*   **Grafana**: Pre-loaded with standard cluster dashboards to visualize the victim app's metrics. Exposed locally via Ingress on port `3000`.
*   **Alertmanager**: Evaluates the alerting rules and routes fired alerts to our custom webhook receiver. Exposed locally on port `9093`.

### 2. Alert Receiver (`alert-echo`)
A lightweight, in-cluster webhook receiver deployed via raw Kubernetes manifests (`infra/monitoring/alert-echo.yaml`).
*   **Implementation**: A minimalistic Python HTTP server running inside a busybox/python pod.
*   **Function**: Listens on port `8080`, receives HTTP POST requests from Alertmanager, parses the JSON payload, and echoes it to standard output (stdout) for easy log scraping.

## Alerting Rules Contract
We will configure roughly 12 realistic alert rules directly inside the Helm `values-local.yaml` (under `additionalPrometheusRulesMap`). 

**Tuning for Local Sandbox:**
To ensure our local development loops and demos are fast, the `for:` duration (the time a threshold must be breached before firing) will be artificially lowered to `30s` or `1m`. Inline comments will denote standard production thresholds (e.g., `5m` or `15m`).

**Curated Rules Included:**
1. `KubePodCrashLooping`
2. `TargetDown`
3. `HighErrorRate` (HTTP 5xx)
4. `LatencySLOBreach`
5. `MemorySaturation` (Host/Node)
6. `CPUThrottlingHigh`
7. `KubePodNotReady`
8. `PVCSpaceApproachingCapacity`
9. `KubeDeploymentReplicasMismatch`
10. `OOMKilled`
11. `NodeNotReady`
12. `KubeJobFailed`

## Data Flow & Fixture Generation
The end goal of this stack is to produce realistic `.json` fixtures that our future ingestor service can consume.

**`scripts/generate-alert-fixtures.sh`**:
1. Sets up a background process to tail the logs of the `alert-echo` pod.
2. Artificially induces a failure in the `victim` namespace (e.g., forcing a pod into a CrashLoopBackOff or scaling it improperly).
3. Waits for Prometheus to detect the anomaly and Alertmanager to fire the webhook.
4. Extracts the clean JSON payload from the `alert-echo` logs.
5. Saves the payload to `tests/fixtures/alerts/KubePodCrashLooping.json`.
6. Restores the victim environment to a healthy state.

## Interfaces / Makefile Targets
*   `make monitoring-up`: Installs the Helm chart and the `alert-echo` receiver.
*   `make monitoring-down`: Uninstalls the Helm release and deletes the `monitoring` namespace.
*   `make generate-fixtures`: Runs the bash script to capture the JSON alert payloads.
