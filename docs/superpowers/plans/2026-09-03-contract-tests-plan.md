# Port Contract Tests & In-Memory Fakes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the executable proof of cloud-agnosticism: a parametrization-ready test suite and robust in-memory fakes.

**Spec:** `docs/superpowers/specs/2026-09-02-contract-tests-design.md`

## Global Constraints
- **Timing-Sensitive Tests:** Visibility timeouts and TTLs must be tunable via fixture parameters (e.g., `visibility_timeout: float = 0.1`) so slow CI runners do not flake.
- **Concurrency:** Real `asyncio.gather` must be used for concurrency tests, no mocks.
- **Fail-Closed Design:** Sabotage tests MUST verify that the suite catches broken implementations.

---

### Task 1: Package Foundation & In-Memory Fakes

**Files:**
- Create: `libs/ports-testing/pyproject.toml`
- Create: `libs/ports-testing/ports_testing/__init__.py`
- Create: `libs/ports-testing/ports_testing/fakes.py`

- [ ] **Step 1: Workspace Package Setup**
  Initialize `libs/ports-testing` as a `uv` library. Add `pytest`, `pytest-asyncio`, and a relative path dependency to `libs/ports`.
  Ensure `pyproject.toml` uses `[project]` metadata properly and add it to the root workspace members (if it doesn't auto-discover).

- [ ] **Step 2: Implement Fakes (`fakes.py`)**
  Implement fully-functional in-memory adapters for:
  - `Queue`: Use `asyncio.Queue`, `dict` for visibility locks/in-flight messages, and simple deduplication windows using timestamps.
  - `LockService`: Use `asyncio.Lock` and time-based TTLs. Ensure strictly monotonic fencing tokens (e.g., using a global counter per resource).
  - `BlobStore`, `SecretStore`, `AuditSink`: Dict-based storage. `AuditSink` must maintain a monotonic append sequence.

- [ ] **Step 3: Commit**
  Commit the package scaffold, `uv.lock` changes, and `fakes.py`.

---

### Task 2: Contract Suite (Queue & LockService)

**Files:**
- Create: `libs/ports-testing/ports_testing/contracts/queue.py`
- Create: `libs/ports-testing/ports_testing/contracts/lock.py`
- Create: `libs/ports-testing/ports_testing/contracts/__init__.py`

- [ ] **Step 1: Queue Contracts**
  Write tests expecting a `queue_adapter` and `queue_config` fixture.
  Tests must cover:
  - Publish & consume (standard delivery).
  - `nack()` redelivery.
  - Visibility timeout redelivery (tuneable).
  - Dead Letter Queue routing after $N$ failures.
  - Idempotency deduplication.
  - Consumer-group semantics (fan-out correctly).

- [ ] **Step 2: LockService Contracts**
  Write tests expecting a `lock_service` fixture.
  Tests must cover:
  - `asyncio.gather` with 20 contenders; verify only one acquires the lock.
  - TTL expiration allows takeover.
  - `renew()` successfully extends TTL.
  - Fencing tokens are strictly monotonic.
  - Stale lease release does not crash (no-op).

- [ ] **Step 3: Commit**
  Commit the `queue.py` and `lock.py` contract files.

---

### Task 3: Data Store Contracts & Suite Sabotage Tests

**Files:**
- Create: `libs/ports-testing/ports_testing/contracts/stores.py`
- Create: `libs/ports-testing/tests/test_sabotage.py`
- Create: `libs/ports-testing/tests/test_fakes.py`

- [ ] **Step 1: Store Contracts**
  Write contracts in `stores.py` expecting `blob_store`, `secret_store`, and `audit_sink` fixtures. Verify CRUD, immutability, and monotonic sequences.

- [ ] **Step 2: Validate Fakes (`test_fakes.py`)**
  Wire the in-memory fakes from Task 1 into the contract suite via wildcard imports (e.g., `from ports_testing.contracts.queue import *`) and run them to prove the fakes pass the suite.

- [ ] **Step 3: Sabotage Tests (`test_sabotage.py`)**
  Write tests that instantiate deliberately broken adapters (e.g., a `BrokenLockService` that issues static fencing tokens, or a `BrokenQueue` that ignores visibility timeouts).
  Invoke the specific contract test functions against these broken adapters and assert that they raise `AssertionError` or fail as expected. Prove >= 3 properties (e.g., one for Queue, one for Lock, one for Audit).

- [ ] **Step 4: Commit**
  Commit the store contracts, fake validation, and sabotage tests.

---

### Task 4: Documentation

**Files:**
- Create: `libs/ports-testing/README.md`

- [ ] **Step 1: Write `README.md`**
  Write the guide: "How to certify a new adapter in one PR".
  Document exactly which fixtures the adapter author must provide (e.g., `queue_adapter`, `lock_service`) and the exact wildcard import syntax.
  Show a short code example.

- [ ] **Step 2: Run Tests & Commit**
  Run `pytest libs/ports-testing/tests` one last time to ensure everything is perfectly green. Commit the documentation.
