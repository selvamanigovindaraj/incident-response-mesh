# Real Adapters Implementation Plan

## Goal
Implement the first set of cloud-agnostic adapters (`libs/adapters`) against the `libs/ports` interfaces, and prove their compliance using the `libs/ports-testing` suite.

## Context
Spec: `docs/superpowers/specs/2026-09-05-real-adapters-design.md`
Workspace: `libs/adapters`

## Task 1: Package Foundation & Simple Stores
- **Description:** Scaffold the `libs/adapters` package and implement the filesystem and environment-based stores.
- **Steps:**
  1. Initialize `libs/adapters` using `uv` (as a workspace member) and configure `pyproject.toml` with `redis` and `psycopg[pool]` as optional extras.
  2. Implement `EnvSecretStore` (wrapping `os.environ`).
  3. Implement `FsBlobStore` (using `asyncio.to_thread` for non-blocking I/O).
  4. Write a small test file `tests/test_simple_stores.py` that utilizes `ports_testing.contracts` to verify these two adapters.
- **Definition of Done:** Both adapters pass their respective contract test suites perfectly.

## Task 2: Postgres Foundation & PgAuditSink
- **Description:** Set up the local testing environment for Postgres and implement `PgAuditSink`.
- **Steps:**
  1. Add a `docker-compose.yml` to the root (or `libs/adapters/tests`) to spin up Postgres (and Redis for later).
  2. Implement `PgAuditSink` in `adapters/postgres.py`, fulfilling the immutability and append guarantees.
  3. Write a test setup fixture in `tests/conftest.py` that handles `CREATE TABLE` and `REVOKE` for test isolation.
  4. Verify the `PgAuditSink` against the `ports-testing` audit sink contracts.
- **Definition of Done:** `PgAuditSink` successfully passes the contract test suite against a real Postgres container.

## Task 3: Redis Lock Service & ADR
- **Description:** Implement the Redis lock adapter and document the architectural trade-off.
- **Steps:**
  1. Implement `RedisLockService` in `adapters/redis.py` utilizing `SET NX PX`, `INCR` for fencing, and atomic Lua scripts for release/renew.
  2. Write `docs/architecture/decisions/0002-redis-aof-fencing-tokens.md` (or similar next sequence) documenting the single-node Redis + AOF trade-off.
  3. Verify against the lock service contract suite.
- **Definition of Done:** Lock service contract tests are fully green, including the sabotage/atomic release checks.

## Task 4: Redis Stream Queue
- **Description:** Implement the `RedisStreamQueue` with XAUTOCLAIM visibility timeouts and DLQ routing.
- **Steps:**
  1. Implement `publish` (with `SET NX` idempotency dedup).
  2. Implement `consume` (alternating `XAUTOCLAIM` and `XREADGROUP BLOCK`).
  3. Implement delivery tracking (`HINCRBY`) and automatic DLQ routing for messages exceeding `max_deliveries`.
  4. Implement `ack` and `nack`.
  5. Verify against the queue contract tests.
- **Definition of Done:** Queue contract tests (including dedup and redelivery) are fully green against a real Redis container.

## Task 5: Adapter Registry & CI Integration
- **Description:** Build the central registry, verify CI, and finalize documentation.
- **Steps:**
  1. Implement `AdapterRegistry` to cleanly instantiate all the adapters from a configuration mapping.
  2. Update the root `.github/workflows/ci.yml` to spin up Redis and Postgres services for the tests.
  3. Update `libs/adapters/README.md` to include a conformance matrix badge.
- **Definition of Done:** The whole package tests successfully in CI, types do not leak, and documentation is updated.
