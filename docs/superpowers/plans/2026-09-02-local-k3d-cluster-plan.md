# Local k3d Cluster Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a fully automated, reproducible 3-node local Kubernetes cluster using k3d with an embedded local registry and pinned dependencies.

**Architecture:** A Makefile-driven setup wrapping a declarative `k3d.yaml` config (1 server, 2 agents). Dependencies are pinned via `.tool-versions`.

**Tech Stack:** Makefile, k3d, Docker, Kubernetes (kubectl).

**Spec:** `docs/superpowers/specs/2026-09-02-local-k3d-cluster-design.md`

## Global Constraints

- No application workloads, monitoring stack, or service mesh are to be deployed (purely infrastructure setup).
- All cluster definitions must go inside `infra/cluster/`.

---

### Task 1: Initialize `.tool-versions` and Makefile Prerequisites Check

**Files:**
- Create: `.tool-versions`
- Create: `Makefile`

**Interfaces:**
- Produces: `.tool-versions` file with pinned versions and a `Makefile` with `check-prereqs` target for subsequent targets to depend on.

- [ ] **Step 1: Write `.tool-versions`**

```text
k3d 5.6.0
kubectl 1.30.0
helm 3.14.0
```

- [ ] **Step 2: Write Makefile with `check-prereqs` target**

```makefile
.PHONY: check-prereqs
check-prereqs:
	@command -v docker >/dev/null 2>&1 || { echo >&2 "docker is required but not installed. Aborting."; exit 1; }
	@command -v k3d >/dev/null 2>&1 || { echo >&2 "k3d is required but not installed. Aborting."; exit 1; }
	@command -v kubectl >/dev/null 2>&1 || { echo >&2 "kubectl is required but not installed. Aborting."; exit 1; }
	@command -v helm >/dev/null 2>&1 || { echo >&2 "helm is required but not installed. Aborting."; exit 1; }
	@echo "All prerequisites found."
```

- [ ] **Step 3: Run the check**

Run: `make check-prereqs`
Expected: Output stating "All prerequisites found." (Assuming tools are installed on the host. If not, the script correctly catches it).

- [ ] **Step 4: Commit**

```bash
git add .tool-versions Makefile
git commit -m "chore: pin tool versions and add prereq check to Makefile"
```

### Task 2: Create Declarative k3d Config

**Files:**
- Create: `infra/cluster/k3d.yaml`

**Interfaces:**
- Consumes: Tooling from Task 1.
- Produces: `infra/cluster/k3d.yaml` to be used by k3d cluster creation.

- [ ] **Step 1: Write `infra/cluster/k3d.yaml`**

```yaml
apiVersion: k3d.io/v1alpha5
kind: Simple
metadata:
  name: irm-cluster
servers: 1
agents: 2
ports:
  - port: 8080:80
    nodeFilters:
      - loadbalancer
  - port: 8443:443
    nodeFilters:
      - loadbalancer
  - port: 3000:3000
    nodeFilters:
      - loadbalancer
  - port: 9090:9090
    nodeFilters:
      - loadbalancer
  - port: 9093:9093
    nodeFilters:
      - loadbalancer
registries:
  create:
    name: irm-registry
    host: "0.0.0.0"
    hostPort: "5001"
```

- [ ] **Step 2: Validate YAML syntax**

Run: `cat infra/cluster/k3d.yaml` (Check that it visually matches expectations; true testing happens in Task 3).
Expected: File exists and has valid YAML syntax.

- [ ] **Step 3: Commit**

```bash
git add infra/cluster/k3d.yaml
git commit -m "infra: add k3d declarative configuration"
```

### Task 3: Implement Cluster Lifecycle Makefile Targets

**Files:**
- Modify: `Makefile`

**Interfaces:**
- Consumes: `check-prereqs` (Task 1) and `infra/cluster/k3d.yaml` (Task 2).
- Produces: `cluster-up`, `cluster-down`, and `cluster-status` commands.

- [ ] **Step 1: Add lifecycle targets to Makefile**

```makefile
.PHONY: cluster-up
cluster-up: check-prereqs
	k3d cluster create --config infra/cluster/k3d.yaml

.PHONY: cluster-down
cluster-down: check-prereqs
	k3d cluster delete --config infra/cluster/k3d.yaml

.PHONY: cluster-status
cluster-status: check-prereqs
	k3d cluster list
	kubectl get nodes -o wide
```

- [ ] **Step 2: Verify `cluster-up` creates the cluster successfully**

Run: `make cluster-up`
Expected: k3d provisions the 1-server/2-agent cluster and embedded registry successfully.

- [ ] **Step 3: Verify `cluster-status` output**

Run: `make cluster-status`
Expected: `k3d cluster list` shows `irm-cluster` running. `kubectl get nodes` shows 1 server and 2 agents in `Ready` state.

- [ ] **Step 4: Verify `cluster-down` destroys the cluster idempotently**

Run: `make cluster-down`
Expected: Cluster and registry containers are completely removed.

- [ ] **Step 5: Commit**

```bash
git add Makefile
git commit -m "infra: add cluster lifecycle makefile targets"
```

### Task 4: Implement Registry Verification Target

**Files:**
- Modify: `Makefile`

**Interfaces:**
- Consumes: Localhost mapped registry port (5001) and internal registry naming (`k3d-irm-registry:5000`).

- [ ] **Step 1: Add `test-registry` target to Makefile**

```makefile
.PHONY: test-registry
test-registry: check-prereqs
	@echo "Testing registry push..."
	docker pull alpine:latest
	docker tag alpine:latest localhost:5001/test-image:latest
	docker push localhost:5001/test-image:latest
	@echo "Testing registry pull from within cluster..."
	kubectl run registry-test --image=k3d-irm-registry:5000/test-image:latest --restart=Never --rm -i --tty -- command -v sh
```

- [ ] **Step 2: Verify `test-registry` works on an active cluster**

Run: `make cluster-up && make test-registry`
Expected: Alpine pulls, pushes successfully to `localhost:5001`, and `kubectl run` succeeds (outputs `/bin/sh` or similar path), meaning the cluster can resolve `k3d-irm-registry:5000`.

- [ ] **Step 3: Cleanup cluster post-test**

Run: `make cluster-down`
Expected: Clean teardown.

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "test: add make test-registry to verify local registry"
```

### Task 5: Write Setup Documentation

**Files:**
- Create: `docs/setup.md`

**Interfaces:**
- Consumes: All outputs from Tasks 1-4.

- [ ] **Step 1: Write `docs/setup.md`**

```markdown
# Local Setup Guide

This project relies on a local Kubernetes cluster using `k3d`.

## Prerequisites

1. **Docker**: Ensure the Docker daemon is running.
2. **Version Manager**: We use `.tool-versions` (compatible with `asdf` or `mise`) to pin dependencies. Install these pinned versions:
   - `k3d`
   - `kubectl`
   - `helm`

## Available Commands

- `make check-prereqs`: Validates all required CLIs are available.
- `make cluster-up`: Provisions a 3-node k3d cluster with a local registry (`irm-registry`) mapped to localhost:5001. Port bindings include 8080, 8443, 3000, 9090, 9093.
- `make cluster-status`: Prints the status of the k3d cluster and kubernetes nodes.
- `make cluster-down`: Destroys the cluster and local registry.
- `make test-registry`: End-to-end smoke test validating the local registry works internally and externally.
```

- [ ] **Step 2: Verify documentation**

Run: `cat docs/setup.md`
Expected: Output matches exactly.

- [ ] **Step 3: Commit**

```bash
git add docs/setup.md
git commit -m "docs: create cluster setup guide"
```
