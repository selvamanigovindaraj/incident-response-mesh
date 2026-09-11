# Real Adapters Design

## Overview
This specification details the first set of real adapters for the cloud-agnostic seams defined in `libs/ports`. The adapters include `RedisStreamQueue`, `RedisLockService`, `FsBlobStore`, `EnvSecretStore`, and `PgAuditSink`. All adapters must pass the 1.4 conformance test suite (`libs/ports-testing`).

## Package Structure
* **Location:** `libs/adapters`
* **Dependencies:** `redis` and `psycopg[pool]` will be added as optional dependency groups. Consumers can install the package using `uv add "adapters[redis,postgres]"`.
* **Boundary:** Adapter implementations will strictly conform to protocols in `libs.ports.interfaces`. Internal types (like `redis.asyncio.Redis` or `psycopg`) will not leak into the public API signatures.

## Adapter Registry
* **Purpose:** Provides a centralized, configuration-driven way to instantiate and retrieve adapters.
* **Mechanism:** 
  * Accepts a configuration dictionary (mapping config keys to adapter types/URLs).
  * Manages the lifecycle of shared connection clients (e.g., a single Redis pool, a single Postgres pool).
  * Exposes getter methods (e.g., `registry.get_queue(key)`) that lazily initialize adapters injected with the appropriate connection client.

## Data Stores
### 1. EnvSecretStore
* **Mechanism:** Wraps `os.environ`.
* **Behavior:** Read-only dictionary lookup. Raises the standard `SecretError` if a required secret is missing.

### 2. FsBlobStore
* **Mechanism:** Interacts with a local base directory on the filesystem.
* **Concurrency:** File operations (read, write, delete, glob) are offloaded to `asyncio.to_thread` to prevent blocking the async event loop.
* **Ordering:** `list_prefix` globs the directory and sorts lexicographically.

### 3. PgAuditSink
* **Mechanism:** Injects a `psycopg_pool.AsyncConnectionPool`.
* **Schema Assumption:** Assumes an external migration tool manages the `audit_events` table with a `seq BIGSERIAL PRIMARY KEY` and a `payload JSONB` column. 
* **Immutability:** Relies on the DBA executing `REVOKE UPDATE, DELETE ON audit_events FROM <user>;`. This requirement is explicitly documented in the class docstring.
* **Operations:** 
  * `append()` executes `INSERT INTO audit_events (payload) VALUES (%s) RETURNING seq`.
  * `get_events()` executes a `SELECT` query ordered by `seq ASC`.

## Redis Implementations
### 1. RedisLockService
* **Acquire:** Uses `SET <resource_key> <lease_id> NX PX <ttl>`. If successful, it calls `INCR <resource_key>:fencing` to obtain a strictly monotonic fencing token.
* **Release/Renew:** Executes an atomic Lua script that compares the stored `lease_id` against the caller's ID before issuing a `DEL` or `PEXPIRE`. This ensures stale holders cannot release a newer lease.
* **Trade-off (ADR):** Fencing token durability relies on single-node Redis with AOF. The minor theoretical risk of duplicate tokens during a catastrophic node crash before fsync is accepted and will be documented in an ADR, explicitly ruling out Redlock complexity.

### 2. RedisStreamQueue
* **Publish & Dedup:** Dedup is handled by `SET <idempotency_key> "1" NX EX <window>`. The payload is then published via `XADD`. If dedup returns false, publish is skipped.
* **Consume Loop:** Alternates between `XAUTOCLAIM` (fetching timed-out messages) and `XREADGROUP BLOCK` (fetching new messages).
* **DLQ Routing:** 
  * Delivery counts are tracked in a dedicated Redis Hash (`HINCRBY delivery_counts:<msg_id>`).
  * If a message's count exceeds `max_deliveries`, it is published to a DLQ stream via `XADD` and removed from the main stream via `XACK`, bypassing the application layer.
* **Ack/Nack:**
  * `ack()`: Calls `XACK` and deletes the delivery count tracking.
  * `nack(requeue=True)`: No-op; the message visibility timeout expires naturally, allowing `XAUTOCLAIM` to pick it up again.
  * `nack(requeue=False)`: Immediately routes the message to the DLQ and `XACK`s the original.

## Acceptance Criteria
1. Full 1.4 conformance suite passes against real Redis and Postgres (via docker-compose services).
2. Lock release is proven atomic via Lua.
3. Fencing tokens survive Redis restart (handled via documented AOF requirement).
4. DLQ path test: Messages failing 3 times land in the DLQ with metadata.
5. No adapter leaks library types through the port (enforced by `mypy`).
6. Conformance badge is added to the README table: port × adapter × status.
