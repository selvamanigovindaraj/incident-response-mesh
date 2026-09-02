# Monorepo Foundation Design

## Overview
This document outlines the architectural foundation for the Incident Response Mesh monorepo. It establishes a unified Python workspace using `uv`, rigorous continuous integration (CI) quality gates via GitHub Actions, and reproducible local developer environments using Devcontainers.

## 1. Monorepo Architecture & Layout

We are adopting a unified `uv` workspace to manage multiple Python packages in a single repository. This allows strict separation of concerns while maintaining a single, lightning-fast dependency resolution graph (`uv.lock`) at the root.

### Directory Structure
```text
.
├── .devcontainer/             # Reproducible environment config
├── .github/
│   ├── workflows/ci.yml       # GitHub Actions CI matrix
│   └── PULL_REQUEST_TEMPLATE.md
├── docs/
│   ├── adr/
│   │   └── 0001-monorepo-over-polyrepo.md
│   └── superpowers/specs/     # Design documents
├── libs/                      # Shared libraries
│   └── core/                  # Core library package
├── services/                  # Executable services
│   ├── hello-world/           # Skeleton service with Dockerfile
│   └── scenario-runner/       # (Migrated) Existing scenario scripts and tests
├── agents/                    # Future agent implementations
├── mcp/                       # Future Model Context Protocol servers
├── infra/                     # (Existing) Infrastructure manifests
├── chaos/                     # (Existing) Chaos mesh configurations
├── LICENSE                    # MIT License
├── README.md                  # Root project documentation
├── .pre-commit-config.yaml    # Local hooks mirroring CI
└── pyproject.toml             # Root workspace anchor
```

### Workspace Configuration
The root `pyproject.toml` will be purely a workspace anchor and will not build into a package itself:
```toml
[tool.uv.workspace]
members = [
    "libs/*",
    "services/*",
    "agents/*",
    "mcp/*"
]
```

## 2. CI/CD Pipeline (GitHub Actions)

The CI pipeline is designed to be minimal and fast (< 5 minutes total runtime) using native `uv` caching.

### Workflow: Pull Request & Main Validation
- **Path Filtering:** Uses `dorny/paths-filter` to detect which packages within the workspace changed.
- **Dynamic Matrix Job:** For each changed Python package, the CI runs:
  - **Linting & Formatting:** `ruff check .` and `ruff format --check .`
  - **Strict Typechecking:** `mypy . --strict` (strictly enforced on `libs/`, applied workspace-wide).
  - **Unit Tests:** `pytest --cov=. --cov-fail-under=80` (enforcing a hard 80% coverage floor).
- **Docker Build Job:** If `services/hello-world/` changes, a verification step runs `docker build` to ensure the container compiles cleanly.

## 3. Developer Experience

### Devcontainer
To guarantee reproducible local development:
- **Base Image:** `mcr.microsoft.com/devcontainers/python:3.12`
- **Features:** 
  - `ghcr.io/devcontainers/features/docker-in-docker` (for building local service images).
- **Lifecycle:** Automatically runs `uv sync` on creation to prepare the workspace.

### Pre-commit Hooks
`.pre-commit-config.yaml` will be configured to run `ruff` and `mypy`. This provides developers with instant feedback locally before pushing code that would fail the CI gates.

### Pull Request Template
All PRs will automatically populate with a checklist template containing:
1. **Intent:** Summary of what the PR accomplishes.
2. **ADR Link:** Reference to any architectural decisions made.
3. **Test Evidence:** Proof of local testing or CI validation.
4. **Rollback Note:** Instructions for reverting the change safely.

## 4. Acceptance Criteria & Validation Strategy

1. **Green Skeleton Pipeline:** The CI workflow passes on the initial skeleton architecture within 5 minutes.
2. **Type-Gate Verification:** A deliberately introduced type error in `libs/core` causes the CI matrix to fail (which will be verified and then reverted).
3. **Local Sync:** Executing `uv sync && pytest` locally functions correctly across the workspace.
4. **Devcontainer Build:** The Devcontainer successfully boots and runs tests.
5. **PR Template Applied:** Opening a trivial pull request correctly surfaces the requested PR sections.

## 5. Out of Scope
- Security scanners (to be handled in phase 1.2).
- Implementation of actual domain code inside the services or agents.
