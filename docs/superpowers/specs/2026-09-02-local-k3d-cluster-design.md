# Design Specification: Local k3d Cluster Setup

## Overview
This specification details the foundational local Kubernetes cluster infrastructure for the `incident-response-mesh` repository. The goal is a highly reproducible, one-command (`make cluster-up`) setup that brings up a 3-node cluster and a local container registry in under 5 minutes, allowing any reviewer or developer to run the project locally.

## Scope
- **In Scope:** Local cluster configuration (k3d), Makefile automation, local container registry wiring, tool version pinning (`.tool-versions`), and basic setup documentation.
- **Out of Scope:** Application workloads, monitoring stack deployment, chaos tooling, and service mesh installation (these will be handled in subsequent specs).

## 1. Directory Structure & Tooling
- **`.tool-versions`**: Will use `asdf`/`mise` syntax to pin versions for:
  - `k3d`
  - `kubectl`
  - `helm`
- **`docs/setup.md`**: Guide for developers detailing system prerequisites (Docker, `asdf`/`mise`) and available Makefile commands.
- **`infra/cluster/k3d.yaml`**: The primary declarative configuration file for the cluster.
- **`Makefile`**: Entrypoint for all cluster lifecycle actions.

## 2. Cluster Architecture & Configuration (`k3d.yaml`)
We are using `k3d` for its speed and native registry integration. The configuration will explicitly define:

- **Topology**: 3 nodes (1 Server/Control-Plane, 2 Agents/Workers). This multi-node setup ensures scheduling, pod anti-affinity, and network partition scenarios can be meaningfully tested later.
- **Networking**: Default k3d networking and default Ingress Controller (Traefik) remain enabled for this phase.
- **Host Port Mappings** (Bound to the LoadBalancer node):
  - `8080:80` (Default HTTP / Future Mesh Ingress)
  - `8443:443` (Default HTTPS)
  - `3000:3000` (Grafana)
  - `9090:9090` (Prometheus)
  - `9093:9093` (Alertmanager Webhook)
- **Container Registry**: An embedded registry named `irm-registry` will be created automatically by k3d.
  - Internal Cluster Address: `irm-registry:5000`
  - External Localhost Address: `localhost:5001`

## 3. Makefile Workflows
The `Makefile` will abstract all complex commands into simple, memorable targets:

- **`make check-prereqs`**: A silent helper that verifies `docker`, `k3d`, `kubectl`, and `helm` are available on the user's `$PATH`.
- **`make cluster-up`**: 
  - Depends on `check-prereqs`.
  - Executes `k3d cluster create --config infra/cluster/k3d.yaml`.
- **`make cluster-down`**: 
  - Executes `k3d cluster delete --config infra/cluster/k3d.yaml`.
  - Fully idempotent (safe to run repeatedly, leaves no orphaned resources).
- **`make cluster-status`**:
  - Executes `k3d cluster list`.
  - Executes `kubectl get nodes -o wide`.
- **`make test-registry`**: 
  - A dedicated test target for CI and developers to verify the registry works end-to-end.
  - Action 1: Pulls `alpine:latest` and tags it as `localhost:5001/test-image:latest`.
  - Action 2: Pushes to `localhost:5001/test-image:latest`.
  - Action 3: Deploys a temporary Pod via `kubectl run` that pulls `irm-registry:5000/test-image:latest`.
  - Action 4: Cleans up the test Pod.

## Acceptance Criteria
- `make cluster-up` produces a healthy 3-node cluster from a clean machine in < 5 minutes.
- `kubectl get nodes` shows all nodes in a `Ready` state.
- `make cluster-down && make cluster-up` safely resets the environment idempotently.
- `make test-registry` successfully completes the push/pull cycle.
- Dependencies are strictly pinned in `.tool-versions`.
