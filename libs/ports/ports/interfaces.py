from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from ports.types import Lease, Message

__all__ = [
    "AuditSink",
    "BlobStore",
    "LockService",
    "Queue",
    "SecretStore",
]


@runtime_checkable
class Queue(Protocol):
    """
    Asynchronous message queue port for decoupling producers and consumers.
    """

    async def publish(self, topic: str, msg: Message) -> None:
        """
        Publishes a message to the specified topic.

        Guarantees:
        - Delivery: At-least-once delivery. Messages may be redelivered upon network partitions
          or unacknowledged timeouts; consumers should rely on msg.idempotency_key for deduplication.
        - Durability: Message is durably written to the broker/transport before returning.
        - Ordering: Best-effort or partition-ordered depending on underlying adapter.
        """
        ...

    def consume(self, topic: str, group: str) -> AsyncIterator[Message]:
        """
        Streams messages from the specified topic as part of a consumer group.

        Guarantees:
        - Delivery: Yields messages under an adapter-specific visibility timeout.
          If not acknowledged before the timeout expires, the message becomes eligible for redelivery.
        - Ordering: Messages within the same partition/group are yielded in arrival order.
        - Concurrency: Multiple consumers in the same group load-balance topic partitions.
        """
        ...

    async def ack(self, msg: Message) -> None:
        """
        Acknowledges successful processing of a message.

        Guarantees:
        - Durability: Permanently marks the message as processed, committing the offset or removing
          it from the queue to prevent redelivery under normal operation.
        """
        ...

    async def nack(self, msg: Message, requeue: bool = True) -> None:
        """
        Negatively acknowledges a message when processing fails.

        Guarantees:
        - Requeue Semantics: If requeue=True, returns the message to the queue for retry
          (subject to adapter retry policies). If requeue=False, routes the message directly
          to a Dead Letter Queue (DLQ) or drops it according to provider configuration.
        """
        ...


@runtime_checkable
class LockService(Protocol):
    """
    Distributed lock port for mutual exclusion across mesh nodes.
    """

    async def acquire(self, resource: str, ttl: int) -> Lease:
        """
        Attempts to acquire a mutually exclusive distributed lock on the specified resource.

        Guarantees:
        - Mutual Exclusion: Exactly one holder can hold the lock for a resource at any time.
        - Expiration: The lock automatically expires after `ttl` seconds unless renewed.
        - Concurrency: Returns a Lease containing a monotonically increasing fencing token
          to prevent stale writer race conditions.
        """
        ...

    async def renew(self, lease: Lease) -> None:
        """
        Renews the validity period of an active lease.

        Guarantees:
        - Durability: Extends the lock's expiration window by the initial TTL.
        - Safety: Fails if the lease has expired, been stolen, or been revoked.
        """
        ...

    async def release(self, lease: Lease) -> None:
        """
        Voluntarily relinquishes the distributed lock.

        Guarantees:
        - Safety: Releases the lock so other contenders can acquire it immediately.
        - Idempotency: Safe to call if the lease has already expired.
        """
        ...


@runtime_checkable
class BlobStore(Protocol):
    """
    Blob storage port for persisting and retrieving unstructured binary artifacts.
    """

    async def put(self, key: str, data: bytes, content_addressing: bool = False) -> str:
        """
        Persists raw binary data under the specified key.

        Guarantees:
        - Durability: Data is durably committed to storage before returning.
        - Consistency: Strong read-after-write consistency for subsequent get operations.
        - Content Addressing: If content_addressing=True, derives the key deterministically
          from the content hash and safely ignores duplicate writes/collisions.
        - Returns: The final storage key.
        """
        ...

    async def get(self, key: str) -> bytes:
        """
        Retrieves raw binary data stored under key.

        Guarantees:
        - Consistency: Strongly consistent read of blob content.
        - Error Handling: Raises exception if key does not exist.
        """
        ...

    async def delete(self, key: str) -> None:
        """
        Deletes the blob stored under key.

        Guarantees:
        - Idempotency: Succeeds even if the key does not exist.
        - Durability: Blob data is permanently removed from backing store.
        """
        ...

    def list(self, prefix: str) -> AsyncIterator[str]:
        """
        Streams keys matching the specified prefix.

        Guarantees:
        - Ordering: Keys are yielded in lexicographical order where supported by provider.
        - Non-blocking: Streams matching keys asynchronously without loading all into memory.
        """
        ...


@runtime_checkable
class SecretStore(Protocol):
    """
    Secret storage port for retrieving sensitive credentials and keys.
    """

    async def get(self, key: str) -> str:
        """
        Retrieves the plaintext secret string for the given key.

        Guarantees:
        - Consistency: Strongly consistent read from backing secret vault on cache miss.
        - Security: Secrets are fetched on-demand; implementation dictates caching contract and TTL.
        """
        ...


@runtime_checkable
class AuditSink(Protocol):
    """
    Audit log sink port for recording tamper-evident system events.
    """

    async def append(self, event: dict[str, Any]) -> int:
        """
        Appends an event payload to the audit log.

        Guarantees:
        - Immutability: Strictly append-only, immutable ledger. Events cannot be modified or deleted.
        - Ordering: Returns a strictly monotonically increasing sequence number representing
          the event's global order in the audit stream.
        - Durability: Synchronously committed to durable storage before returning.
        """
        ...
