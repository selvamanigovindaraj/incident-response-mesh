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
