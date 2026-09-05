# 3. Redis Single-Node AOF with Fencing Tokens

Date: 2026-09-05

## Status

Accepted

## Context

We need a distributed lock mechanism for the Incident Response Mesh to ensure mutual exclusion across nodes, preventing race conditions when updating shared resources or coordinating background tasks.

Typically, achieving distributed consensus and mutual exclusion in a highly available system requires a quorum-based algorithm, such as Redlock (for Redis) or utilizing Zookeeper, etcd, or Consul. However, introducing these adds significant operational complexity, latency, and infrastructure overhead to our deployment model.

Redis provides a robust set of primitives (`SET NX PX` and atomic Lua scripts) for locking, but a single-node Redis instance represents a single point of failure. Furthermore, relying purely on time-based TTLs for locks can be unsafe if a process pauses (e.g., GC pause) or experiences network delays, causing it to believe it still holds a lock after the TTL has expired on the server.

## Decision

We will implement a single-node Redis lock utilizing `SET NX PX` combined with atomic Lua scripts for renewals and releases. To mitigate the inherent risks of this simpler architecture:

1.  **Strictly Monotonic Fencing Tokens:** We combine `SET NX PX` and `INCR` in an atomic Lua script upon lock acquisition to generate a strictly monotonic fencing token alongside the lock lease. Downstream systems (e.g., Postgres or blob stores) must validate this token to enforce optimistic concurrency. If a delayed worker wakes up after losing its lock, its stale token will be rejected by the storage layer.
2.  **Append-Only File (AOF):** We require the single-node Redis to be configured with AOF persistence (`appendonly yes`). This minimizes the window of data loss during a crash and restart, ensuring that fencing counters and lock states are recovered reliably.
    - **`appendfsync` Configuration Trade-off:**
      - `appendfsync everysec` (default / recommended for standard workloads): Fsyncs the AOF buffer in the background once every second. Provides high throughput with negligible latency impact, with a worst-case durability window of at most 1 second of lost writes in an abrupt server or power failure.
      - `appendfsync always`: Performs an fsync after every single write/transaction. Guarantees absolute durability so fencing counters will never roll back even across immediate power loss, but incurs substantial disk I/O latency on every lock acquisition.
      Standard production deployments default to `appendfsync everysec`, acknowledging the ~1-second crash recovery window while relying on downstream fencing validation for data safety.

We intentionally forgo Redlock to keep the infrastructure footprint small and the operational burden low, trading absolute high availability of the lock service for simplicity, provided that our fencing tokens guarantee correctness in the storage layer.

## Consequences

-   **Positive:** Simpler infrastructure (no Zookeeper/etcd or multi-node Redlock clusters to manage).
-   **Positive:** Very low latency lock acquisition and renewal.
-   **Negative:** Single point of failure. If the Redis node goes down, lock acquisition fails until it recovers.
-   **Negative:** Strong reliance on downstream storage systems correctly implementing and checking fencing tokens to prevent split-brain data corruption.
-   **Trade-off:** Durability vs. performance in `appendfsync`: `appendfsync everysec` risks up to 1 second of lost operations upon an ungraceful crash (potentially allowing fencing token rollback), whereas `appendfsync always` completely closes this window at the cost of disk I/O throughput on every lock acquisition.
