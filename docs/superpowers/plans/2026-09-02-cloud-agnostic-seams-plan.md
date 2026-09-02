# Cloud-Agnostic Seams Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the cloud-agnostic seams (Python Protocols) and shared DTOs that will act as the contract for all infrastructure adapters.

**Architecture:** A new workspace package `libs/ports` containing Pydantic-based DTOs and `@runtime_checkable` asynchronous Python Protocols.

**Tech Stack:** Python 3.12, `uv`, `pydantic`, `mypy`, `pytest`

**Spec:** docs/superpowers/specs/2026-09-02-cloud-agnostic-seams-design.md

## Global Constraints
- Python requirement is strictly `>=3.12`.
- Package must be a valid `uv` workspace member inside `libs/ports`.
- `mypy --strict` must pass flawlessly on the entire package.
- All interface methods must be fully asynchronous (except generators which are `AsyncIterator`).
- All docstrings must state delivery/ordering/durability guarantees explicitly.

---

### Task 1: Package Setup & ADR-002

**Files:**
- Create: `libs/ports/pyproject.toml`
- Create: `libs/ports/ports/__init__.py`
- Create: `docs/adr/0002-cloud-agnostic-seams.md`

**Interfaces:**
- Produces: The `libs/ports` package anchor and ADR documentation.

- [ ] **Step 1: Write `libs/ports/pyproject.toml`**

```toml
[project]
name = "ports"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.0.0"
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "mypy>=1.9.0",
    "ruff>=0.3.0"
]
```

- [ ] **Step 2: Initialize module**

```python
# libs/ports/ports/__init__.py
# Empty initialization file
```

- [ ] **Step 3: Write ADR-002**

Create `docs/adr/0002-cloud-agnostic-seams.md` recording the decision to abstract Queues, Locks, Blobs, Secrets, and Audits, while deliberately NOT abstracting the Postgres checkpointer (handled by LangGraph) or the Kubernetes API.

- [ ] **Step 4: Verify workspace**

Run: `uv sync` from the repository root to ensure the new package is recognized.
Expected: Success

- [ ] **Step 5: Commit**

```bash
git add libs/ports/pyproject.toml libs/ports/ports/__init__.py docs/adr/0002-cloud-agnostic-seams.md
git commit -m "chore: setup ports package and ADR-002"
```

---

### Task 2: Shared Types (`ports/types.py`)

**Files:**
- Create: `libs/ports/ports/types.py`

**Interfaces:**
- Produces: `Message` and `Lease` Pydantic models to be consumed by the protocol interfaces.

- [ ] **Step 1: Write `ports/types.py`**

```python
# libs/ports/ports/types.py
from typing import Any, Dict
from pydantic import BaseModel, Field

class Lease(BaseModel):
    """
    Represents a distributed lock lease.
    """
    token: str = Field(description="Opaque lease identifier used for renewals/releases")
    fence: int = Field(description="Monotonically increasing fencing token for optimistic concurrency")

class Message(BaseModel):
    """
    The standard envelope for all Queue communications.
    """
    payload: Dict[str, Any]
    headers: Dict[str, str] = Field(default_factory=dict)
    trace_context: Dict[str, str] = Field(
        default_factory=dict, 
        description="Reserved for 8.1 tracing injection"
    )
    idempotency_key: str
    schema_version: str = Field(
        default="1.0",
        description="Version of the payload schema to allow backwards-compatible routing"
    )
```

- [ ] **Step 2: Typecheck**

Run: `cd libs/ports && uv run mypy ports/types.py --strict`
Expected: Success

- [ ] **Step 3: Commit**

```bash
git add libs/ports/ports/types.py
git commit -m "feat: add shared Message and Lease types"
```

---

### Task 3: Protocol Interfaces (`ports/interfaces.py`)

**Files:**
- Create: `libs/ports/ports/interfaces.py`

**Interfaces:**
- Consumes: `Message` and `Lease` from `ports.types`.
- Produces: `@runtime_checkable` Python Protocols (`Queue`, `LockService`, `BlobStore`, `SecretStore`, `AuditSink`).

- [ ] **Step 1: Write `ports/interfaces.py`**

Write the file using `typing.Protocol` and `typing.runtime_checkable`. Implement `Queue`, `LockService`, `BlobStore`, `SecretStore`, and `AuditSink` with fully asynchronous methods (`async def` or `AsyncIterator`). Ensure every method has a docstring explicitly stating delivery, ordering, and durability guarantees (e.g., at-least-once delivery for `Queue.publish`, append-only immutable ledger for `AuditSink.append`).

- [ ] **Step 2: Typecheck**

Run: `cd libs/ports && uv run mypy ports/interfaces.py --strict`
Expected: Success

- [ ] **Step 3: Commit**

```bash
git add libs/ports/ports/interfaces.py
git commit -m "feat: define cloud-agnostic python protocols"
```

---

### Task 4: Validation & Placeholder Tests

**Files:**
- Create: `libs/ports/tests/test_imports.py`

**Interfaces:**
- Consumes: All modules in `libs/ports`.
- Produces: Test suite verifying `runtime_checkable` behavior and import syntax.

- [ ] **Step 1: Write placeholder tests**

```python
# libs/ports/tests/test_imports.py
from ports.interfaces import Queue, LockService, BlobStore, SecretStore, AuditSink
from ports.types import Message, Lease

def test_imports_and_instantiation() -> None:
    # Ensure types can be instantiated
    lease = Lease(token="test", fence=1)
    msg = Message(payload={"data": "test"}, idempotency_key="123")
    
    assert lease.fence == 1
    assert msg.schema_version == "1.0"
    
    # Ensure protocols are runtime checkable
    class DummyQueue:
        pass
        
    assert not isinstance(DummyQueue(), Queue)
```

- [ ] **Step 2: Run test suite and typechecks**

Run: `cd libs/ports && uv run pytest tests/ && uv run mypy . --strict`
Expected: 1/1 tests passing, mypy fully green.

- [ ] **Step 3: Commit**

```bash
git add libs/ports/tests/
git commit -m "test: add validation tests for ports library"
```
