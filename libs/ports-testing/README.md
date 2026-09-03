# `ports-testing`: Port Contract Test Suite & In-Memory Fakes

`ports-testing` provides reusable, parametrization-ready contract test suites and high-fidelity in-memory fakes for the core hexagonal architecture ports defined in `libs/ports`.

It is designed to make verifying and certifying any new cloud or infrastructure adapter (e.g. AWS SQS, GCP Pub/Sub, Redis Lock, S3, Azure Key Vault) trivial in a single PR.

---

## How to Certify a New Adapter in One PR

To certify a new adapter implementation:

1. **Add dependencies**: Add `ports-testing` and `ports` as test dependencies in your adapter's `pyproject.toml`.
2. **Create a test file**: In your adapter test suite (e.g., `tests/test_contract.py`), import the relevant contract test suite using the **wildcard import syntax**.
3. **Provide required pytest fixtures**: Implement fixture(s) providing an instance of your adapter (and optional configuration fixtures to tune timing/error types).
4. **Run `pytest`**: All contract tests will be discovered and executed against your adapter automatically. When all tests pass, your adapter is certified!

---

## Contract Suites & Fixture Reference

### 1. Queue Contract Suite

Import syntax:
```python
from ports_testing.contracts.queue import *
```

#### Required Fixtures

| Fixture Name | Type | Description |
| :--- | :--- | :--- |
| `queue_adapter` | `ports.interfaces.Queue` | An instance of your queue adapter to test. Can be an async fixture yielding the instance and cleaning up resources on teardown. |

#### Optional Configuration Fixtures

| Fixture Name | Type | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `queue_config` | `ports_testing.contracts.queue.QueueConfig` | `QueueConfig()` | Dataclass configuring timing and queue behaviors. |

`QueueConfig` parameters:
- `visibility_timeout` (float, default: `0.2`): Duration in seconds before an unacknowledged message is redelivered.
- `max_retries` (int, default: `2`): Number of nack/failure retries before routing to DLQ.
- `dedup_window` (float, default: `0.5`): Idempotency window in seconds.
- `dlq_suffix` (str, default: `".dlq"`): Suffix appended to the topic name for DLQ verification.
- `empty_check_timeout` (float, default: `0.15`): Timeout in seconds when verifying no extra messages are delivered.
- `redelivery_timeout` (float, default: `2.0`): Timeout in seconds when waiting for redelivery after visibility timeout.

#### Tested Guarantees
- Standard publish and consume with message headers and payloads preserved.
- Negative acknowledgment (`nack(msg, requeue=True)`) redelivery.
- Automatic redelivery upon visibility timeout expiration.
- Eviction to Dead Letter Queue (DLQ) after `max_retries`.
- Immediate routing to DLQ on `nack(msg, requeue=False)`.
- Idempotency key deduplication within `dedup_window`.
- Consumer group fan-out (independent delivery across distinct consumer groups).

---

### 2. LockService Contract Suite

Import syntax:
```python
from ports_testing.contracts.lock import *
```

#### Required Fixtures

| Fixture Name | Type | Description |
| :--- | :--- | :--- |
| `lock_service` | `ports.interfaces.LockService` | An instance of your distributed lock adapter. |

#### Tested Guarantees
- Mutual exclusion under heavy concurrency (`asyncio.gather` with 20 contenders; exactly 1 succeeds).
- Automatic lock expiration after TTL and subsequent takeover by another contender.
- Lease renewal (`renew(lease)`) extending lock TTL.
- Strictly monotonically increasing fencing tokens across sequential lock acquisitions.
- Stale/expired lease release is safe and non-blocking (no-op).

---

### 3. Data Store Contract Suites (BlobStore, SecretStore, AuditSink)

Import syntax:
```python
from ports_testing.contracts.stores import *
```

#### BlobStore

- **Required Fixture:** `blob_store` returning `ports.interfaces.BlobStore`.
- **Optional Fixture:** `blob_store_config` returning `BlobStoreConfig(expected_not_found_error=...)`. Default expects `(KeyError, FileNotFoundError, LookupError, RuntimeError)`.
- **Tested Guarantees:**
  - Binary-exact CRUD (`put`, `get`, `delete`).
  - Safe error raising on nonexistent blob retrieval.
  - Strong consistency on overwrite.
  - Idempotent delete (succeeds without error even if the key does not exist).
  - Deterministic content addressing (`put(..., content_addressing=True)`) embedding SHA-256 digest.
  - Asynchronous prefix listing (`list(prefix)`) yielding keys in lexicographical order.
  - Automatic `try...finally` resource cleanup preventing leaked blobs on external stores.

#### SecretStore

- **Required Fixture:** `secret_store` returning `ports.interfaces.SecretStore`.
- **Optional Fixture:** `secret_store_config` returning `SecretStoreConfig(known_key=..., known_value=..., missing_key=..., expected_error=...)`.
- **Tested Guarantees:**
  - Strongly consistent retrieval of plaintext secret string for existing key.
  - Raising expected error on nonexistent or deleted secret key.

#### AuditSink

- **Required Fixture:** `audit_sink` returning `ports.interfaces.AuditSink`.
- **Optional Inspection:** If the sink exposes `get_events()` or `read_events()`, the contract verifies payload immutability against caller mutation. Otherwise, immutability assertion skips cleanly (`pytest.skip`).
- **Tested Guarantees:**
  - Strictly monotonically increasing sequence numbers returned by `append()`.
  - Unique monotonic sequence numbers under concurrent appends (`asyncio.gather`).
  - Ledger immutability (in-place modification of caller event dict does not alter stored audit log).

---

## Code Examples

### Certifying a Queue Adapter (e.g. SQS, Redis, RabbitMQ)

```python
# tests/test_my_queue_adapter_contract.py
from collections.abc import AsyncIterator
import pytest_asyncio
from ports.interfaces import Queue
from ports_testing.contracts.queue import *
from my_adapter.queue import MyQueueAdapter


@pytest_asyncio.fixture
async def queue_adapter(queue_config: QueueConfig) -> AsyncIterator[Queue]:
    # Initialize adapter configured for test environment
    adapter = MyQueueAdapter(
        endpoint_url="http://localhost:4566",
        visibility_timeout=queue_config.visibility_timeout,
    )
    await adapter.connect()
    try:
        yield adapter
    finally:
        await adapter.teardown_and_disconnect()
```

### Certifying a BlobStore Adapter (e.g. S3, GCS, Azure Blob)

```python
# tests/test_my_blob_store_contract.py
import pytest
from ports.interfaces import BlobStore
from ports_testing.contracts.stores import *
from my_adapter.blob import S3BlobStore


@pytest.fixture
def blob_store() -> BlobStore:
    return S3BlobStore(bucket_name="mesh-contract-test-bucket")


@pytest.fixture
def blob_store_config() -> BlobStoreConfig:
    from botocore.exceptions import ClientError
    return BlobStoreConfig(expected_not_found_error=(ClientError, KeyError))
```

---

## In-Memory Fakes

`ports-testing` also exports production-grade in-memory fakes for unit and integration testing without external cloud dependencies:

```python
from ports_testing.fakes import (
    InMemoryAuditSink,
    InMemoryBlobStore,
    InMemoryLockService,
    InMemoryQueue,
    InMemorySecretStore,
)

queue = InMemoryQueue(visibility_timeout=0.2, max_retries=3)
lock = InMemoryLockService()
blobs = InMemoryBlobStore()
secrets = InMemorySecretStore({"DATABASE_URL": "sqlite:///:memory:"})
audit = InMemoryAuditSink()
```
