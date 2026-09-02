# Cloud-Agnostic Seams Design

## Overview
This document defines the core infrastructure contracts (Python Protocols) for the Incident Response Mesh. By abstracting Queues, Locks, Blobs, Secrets, and Audit Logs behind strict, un-implemented interfaces, we guarantee that our agents and services remain portable across AWS, GCP, and local environments (validating the 10.2 agnosticism proof).

## 1. Package Structure
The interfaces will be packaged as a new workspace member: `libs/ports`.
```text
libs/ports/
├── pyproject.toml
├── ports/
│   ├── __init__.py
│   ├── types.py       # Pydantic models (Message, Lease)
│   └── interfaces.py  # Python Protocols (@runtime_checkable)
└── tests/
    └── test_imports.py # Placeholder to verify mypy and imports
```

## 2. Shared Types (`ports/types.py`)
Data transfer objects implemented as Pydantic BaseModels to enforce schemas at the I/O boundary.

- **Lease**: Represents a distributed lock.
  - `token: str`: Opaque identifier for renewal/release.
  - `fence: int`: Monotonically increasing fencing token for optimistic concurrency.
- **Message**: The standard queue envelope.
  - `payload: Dict[str, Any]`
  - `headers: Dict[str, str]` (defaults to empty dict)
  - `trace_context: Dict[str, str]` (Reserved for 8.1 tracing injection)
  - `idempotency_key: str`
  - `schema_version: str` (defaults to "1.0")

## 3. Protocol Interfaces (`ports/interfaces.py`)
All interfaces use fully asynchronous I/O methods. Each method requires an exhaustive docstring explicitly defining its delivery, ordering, and durability guarantees.

1. **`Queue`**
   - `async def publish(self, topic: str, msg: Message) -> None`
     - Guarantee: At-least-once delivery.
   - `def consume(self, topic: str, group: str) -> AsyncIterator[Message]`
     - Guarantee: Yields messages under a visibility timeout.
   - `async def ack(self, msg: Message) -> None`
   - `async def nack(self, msg: Message, requeue: bool = True) -> None` (DLQ semantics if `requeue=False`)

2. **`LockService`**
   - `async def acquire(self, resource: str, ttl: int) -> Lease`
     - Guarantee: Mutually exclusive lock. Expires absolute to TTL unless renewed.
   - `async def renew(self, lease: Lease) -> None`
   - `async def release(self, lease: Lease) -> None`

3. **`BlobStore`**
   - `async def put(self, key: str, data: bytes, content_addressing: bool = False) -> str`
     - Guarantee: Returns final key. If `content_addressing=True`, ignores collisions safely.
   - `async def get(self, key: str) -> bytes`
   - `async def delete(self, key: str) -> None`
   - `def list(self, prefix: str) -> AsyncIterator[str]`

4. **`SecretStore`**
   - `async def get(self, key: str) -> str`
     - Guarantee: Strongly consistent read on cache miss. Implementation dictates caching contract.

5. **`AuditSink`**
   - `async def append(self, event: Dict[str, Any]) -> int`
     - Guarantee: Strictly append-only, immutable ledger. Returns monotonically increasing sequence number.

## 4. ADR-002: Cloud-Agnostic Seams
We will document our abstraction boundaries in `docs/adr/0002-cloud-agnostic-seams.md`.
- **Abstracted:** The 5 core I/O ports (Queues, Locks, Blobs, Secrets, Audits).
- **Not Abstracted (Deliberate):** 
  - *Postgres Checkpointer:* LangGraph already provides a Checkpointer API. Wrapping an abstraction in another abstraction is a leaky trap.
  - *Kubernetes API:* K8s is our baseline deployment abstraction. Creating a "cloud-agnostic container port" is an anti-pattern.

## 5. Acceptance Criteria
- `libs/ports` passes `mypy --strict`.
- Protocols are `typing.runtime_checkable`.
- Envelope includes `trace_context` and `schema_version`.
- Docstrings contain explicit guarantees for all methods.
- ADR-002 merged alongside the code.
- Interfaces successfully imported by a placeholder test suite.
