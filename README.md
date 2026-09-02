# Incident Response Mesh

Incident Response Mesh is an autonomous, distributed incident management and response framework built as a Python monorepo.

## Monorepo Structure

The repository is organized as a unified `uv` workspace:

```text
.
├── libs/              # Shared libraries and packages (e.g., core domain models, utilities)
├── services/          # Executable services and background workers
├── agents/            # Incident response autonomous agents
├── mcp/               # Model Context Protocol servers
├── infra/             # Infrastructure manifests and configurations
├── chaos/             # Chaos mesh experiments and failure scenarios
├── docs/              # Documentation, specifications, and Architecture Decision Records (ADRs)
├── pyproject.toml     # Root workspace configuration
└── README.md          # Project overview and setup instructions
```

## Prerequisites

- **Python:** `>= 3.12`
- **Package Manager:** [`uv`](https://docs.astral.sh/uv/)

## Getting Started

### 1. Install dependencies across the workspace

```bash
uv sync
```

### 2. Running commands within packages

Run commands in specific packages using `uv run` or by changing into package directories:

```bash
# Run tests for a specific package
cd services/scenario-runner && uv run pytest

# Run formatting and linting
uv run ruff check .
uv run ruff format .
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
