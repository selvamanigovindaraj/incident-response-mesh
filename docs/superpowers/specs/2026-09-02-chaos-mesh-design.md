# Chaos Mesh & Foundation Experiments Design

## Context
To train and evaluate the incident response agents within our mesh, we require a repeatable, deterministic mechanism for injecting failures into the victim environment. This specification details the installation of Chaos Mesh, the configuration of strict RBAC boundaries, and the codification of five foundational chaos experiments.

## Architecture & Security

### 1. Chaos Mesh Installation
We will deploy the official Chaos Mesh Helm chart into the `chaos` namespace.
*   **RBAC Scoping**: To prevent collateral damage to the monitoring stack or the future mesh control plane, Chaos Mesh will be explicitly configured with `controllerManager.targetNamespace=victim`. It will ignore and reject any chaos experiments attempting to target other namespaces.
*   **Dashboard**: The Chaos Dashboard will be installed but not exposed via Traefik Ingress. Instead, it will be accessed ad-hoc via a `Makefile` port-forward command (`localhost:2333`).

## The Experiment Catalog
Five declarative YAML manifests will be created in `chaos/experiments/`. To keep local feedback loops fast, every experiment will have a hardcoded `duration: 60s`.

1.  **`pod-kill.yaml`** (`PodChaos`)
    *   *Target*: `frontend-proxy`
    *   *Action*: Pod failure (kills the pod).
    *   *Expected Alert*: `TargetDown` or `KubeDeploymentReplicasMismatch`.
2.  **`network-delay.yaml`** (`NetworkChaos`)
    *   *Target*: `recommendation`
    *   *Action*: Injects a constant `300ms` delay to all outgoing traffic.
    *   *Expected Alert*: `LatencySLOBreach`.
3.  **`network-partition.yaml`** (`NetworkChaos`)
    *   *Target*: Communication between `frontend` and `cart`.
    *   *Action*: Drops 100% of packets between the two specific deployments.
    *   *Expected Alert*: `HighErrorRate`.
4.  **`cpu-stress.yaml`** (`StressChaos`)
    *   *Target*: `load-generator`
    *   *Action*: Spikes 1 CPU core to 100% utilization.
    *   *Expected Alert*: `CPUThrottlingHigh`.
5.  **`dns-failure.yaml`** (`DNSChaos`)
    *   *Target*: `payment`
    *   *Action*: Spoofs DNS responses, returning errors for internal cluster DNS lookups.
    *   *Expected Alert*: `HighErrorRate`.

## Runner Script & Interfaces

### 1. `scripts/run-chaos.sh`
A bash utility to safely orchestrate an experiment's lifecycle.
*   **Invocation**: `scripts/run-chaos.sh pod-kill`
*   **Workflow**:
    1. Parses the target YAML file to extract the `duration` value.
    2. Applies the manifest via `kubectl`.
    3. Displays a countdown timer in the terminal.
    4. Automatically executes `kubectl delete -f` when the timer expires to actively purge the experiment and clean up underlying iptables/tc/qdiscs.

### 2. Makefile Targets
*   `make chaos-up`: Installs the Chaos Mesh Helm chart.
*   `make chaos-down`: Uninstalls the Helm release and deletes the `chaos` namespace.
*   `make chaos-dashboard`: Initiates a port-forward to `localhost:2333`.
*   `make chaos RUN=<experiment>`: A proxy wrapper that executes `scripts/run-chaos.sh $RUN`.
