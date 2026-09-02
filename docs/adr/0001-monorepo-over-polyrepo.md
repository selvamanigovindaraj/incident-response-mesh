# 1. Monorepo via uv Workspace
Date: 2026-09-02

## Status
Accepted

## Context
We need a structure to hold shared schemas, microservices, agents, and MCP servers that can be tested cross-cuttingly without dependency hell.

## Decision
We will use a Python monorepo driven by a single `uv` workspace. Each domain boundary gets its own package (`services/`, `libs/`, etc.).

## Consequences
- Faster CI execution.
- Single lockfile resolution across all internal packages.
- Prevents version drift between internal consumers and providers.
