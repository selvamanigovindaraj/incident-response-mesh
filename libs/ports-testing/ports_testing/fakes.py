"""
In-memory fakes for cloud-agnostic ports interfaces.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from ports.types import Lease, Message


class LockError(Exception):
    """Base exception for lock service errors."""


class LockAcquisitionError(LockError):
    """Raised when a lock cannot be acquired."""


class LockRenewalError(LockError):
    """Raised when renewing a lease fails (e.g., expired or revoked)."""


class BlobNotFoundError(KeyError):
    """Raised when a blob key is not found."""


class SecretNotFoundError(KeyError):
    """Raised when a secret key is not found."""


@dataclass
class _InFlightDelivery:
    topic: str
    group: str
    original_msg: Message
    delivery_msg: Message
    receipt_handle: str
    timer_task: asyncio.Task[None] | None = None


@dataclass
class _ActiveLease:
    lease: Lease
    expires_at: float
    ttl: float


class InMemoryQueue:
    """
    In-memory message queue supporting pub/sub, consumer groups, visibility timeouts,
    automatic DLQ routing, and idempotency deduplication.
    """

    def __init__(
        self,
        visibility_timeout: float = 30.0,
        max_retries: int = 3,
        dedup_window: float = 300.0,
        dlq_suffix: str = ".dlq",
    ) -> None:
        self.visibility_timeout = float(visibility_timeout)
        self.max_retries = int(max_retries)
        self.dedup_window = float(dedup_window)
        self.dlq_suffix = str(dlq_suffix)

        self._lock = asyncio.Lock()
        self._published_history: dict[str, list[Message]] = defaultdict(list)
        self._groups_by_topic: dict[str, set[str]] = defaultdict(set)
        self._group_queues: dict[tuple[str, str], asyncio.Queue[Message]] = {}
        self._dedup_records: dict[tuple[str, str], float] = {}

        self._in_flight: dict[str, _InFlightDelivery] = {}
        self._delivery_attempts: dict[tuple[str, str, str], int] = defaultdict(int)
        self.dlq: dict[str, list[Message]] = defaultdict(list)

    def _get_or_create_group_queue(
        self, topic: str, group: str
    ) -> asyncio.Queue[Message]:
        key = (topic, group)
        if key not in self._group_queues:
            q: asyncio.Queue[Message] = asyncio.Queue()
            self._group_queues[key] = q
            self._groups_by_topic[topic].add(group)
            for historic_msg in self._published_history[topic]:
                q.put_nowait(historic_msg)
        return self._group_queues[key]

    async def publish(self, topic: str, msg: Message) -> None:
        """
        Publishes a message to the specified topic with idempotency deduplication.
        """
        now = time.monotonic()
        if msg.idempotency_key and self.dedup_window > 0:
            dedup_key = (topic, msg.idempotency_key)
            if dedup_key in self._dedup_records:
                last_published = self._dedup_records[dedup_key]
                if (now - last_published) < self.dedup_window:
                    return  # Deduplicated: drop silently
            self._dedup_records[dedup_key] = now

        # Prune old dedup entries periodically to avoid memory growth
        if len(self._dedup_records) > 2000:
            cutoff = now - self.dedup_window
            self._dedup_records = {
                k: ts for k, ts in self._dedup_records.items() if ts >= cutoff
            }

        self._published_history[topic].append(msg)
        for group in list(self._groups_by_topic[topic]):
            q = self._get_or_create_group_queue(topic, group)
            q.put_nowait(msg)

    async def consume(self, topic: str, group: str) -> AsyncIterator[Message]:
        """
        Streams messages from topic as part of a consumer group under a visibility timeout.
        """
        group_queue = self._get_or_create_group_queue(topic, group)
        while True:
            msg = await group_queue.get()
            receipt_handle = uuid.uuid4().hex
            headers = dict(msg.headers)
            headers["_receipt_handle"] = receipt_handle
            headers["_group"] = group
            headers["_topic"] = topic
            delivery_msg = msg.model_copy(update={"headers": headers})

            in_flight = _InFlightDelivery(
                topic=topic,
                group=group,
                original_msg=msg,
                delivery_msg=delivery_msg,
                receipt_handle=receipt_handle,
            )

            async with self._lock:
                self._in_flight[receipt_handle] = in_flight
                timer_task = asyncio.create_task(
                    self._visibility_timeout_handler(
                        receipt_handle, self.visibility_timeout
                    )
                )
                in_flight.timer_task = timer_task

            yield delivery_msg

    async def _visibility_timeout_handler(
        self, receipt_handle: str, timeout: float
    ) -> None:
        try:
            await asyncio.sleep(timeout)
            async with self._lock:
                in_flight = self._in_flight.pop(receipt_handle, None)
                if in_flight is None:
                    return
                attempt_key = (
                    in_flight.topic,
                    in_flight.group,
                    in_flight.original_msg.idempotency_key,
                )
                self._delivery_attempts[attempt_key] += 1
                if self._delivery_attempts[attempt_key] >= self.max_retries:
                    self._delivery_attempts.pop(attempt_key, None)
                    await self._route_to_dlq(
                        in_flight.topic,
                        in_flight.original_msg,
                        reason="visibility_timeout_retries_exceeded",
                    )
                else:
                    q = self._get_or_create_group_queue(
                        in_flight.topic, in_flight.group
                    )
                    q.put_nowait(in_flight.original_msg)
        except asyncio.CancelledError:
            pass

    async def ack(self, msg: Message) -> None:
        """
        Acknowledges successful processing of a message, removing it from in-flight tracking.
        """
        async with self._lock:
            receipt_handle = msg.headers.get("_receipt_handle")
            in_flight: _InFlightDelivery | None = None
            if receipt_handle and receipt_handle in self._in_flight:
                in_flight = self._in_flight.pop(receipt_handle)
            else:
                msg_topic = msg.headers.get("_topic")
                msg_group = msg.headers.get("_group")
                # Fallback to match by idempotency key (scoped by topic and group if available)
                for rh, item in list(self._in_flight.items()):
                    if item.original_msg.idempotency_key == msg.idempotency_key:
                        if msg_topic and item.topic != msg_topic:
                            continue
                        if msg_group and item.group != msg_group:
                            continue
                        in_flight = self._in_flight.pop(rh)
                        break

            if in_flight is not None:
                if in_flight.timer_task and not in_flight.timer_task.done():
                    in_flight.timer_task.cancel()
                attempt_key = (
                    in_flight.topic,
                    in_flight.group,
                    in_flight.original_msg.idempotency_key,
                )
                self._delivery_attempts.pop(attempt_key, None)

    async def nack(self, msg: Message, requeue: bool = True) -> None:
        """
        Negatively acknowledges a message. If requeue=True, redelivers or routes to DLQ after max_retries.
        If requeue=False, routes immediately to DLQ.
        """
        async with self._lock:
            receipt_handle = msg.headers.get("_receipt_handle")
            in_flight: _InFlightDelivery | None = None
            if receipt_handle and receipt_handle in self._in_flight:
                in_flight = self._in_flight.pop(receipt_handle)
            else:
                msg_topic = msg.headers.get("_topic")
                msg_group = msg.headers.get("_group")
                # Fallback to match by idempotency key (scoped by topic and group if available)
                for rh, item in list(self._in_flight.items()):
                    if item.original_msg.idempotency_key == msg.idempotency_key:
                        if msg_topic and item.topic != msg_topic:
                            continue
                        if msg_group and item.group != msg_group:
                            continue
                        in_flight = self._in_flight.pop(rh)
                        break

            if in_flight is None:
                return

            if in_flight.timer_task and not in_flight.timer_task.done():
                in_flight.timer_task.cancel()

            attempt_key = (
                in_flight.topic,
                in_flight.group,
                in_flight.original_msg.idempotency_key,
            )
            if not requeue:
                self._delivery_attempts.pop(attempt_key, None)
                await self._route_to_dlq(
                    in_flight.topic,
                    in_flight.original_msg,
                    reason="nack_without_requeue",
                )
            else:
                self._delivery_attempts[attempt_key] += 1
                if self._delivery_attempts[attempt_key] >= self.max_retries:
                    self._delivery_attempts.pop(attempt_key, None)
                    await self._route_to_dlq(
                        in_flight.topic,
                        in_flight.original_msg,
                        reason="nack_max_retries_exceeded",
                    )
                else:
                    q = self._get_or_create_group_queue(
                        in_flight.topic, in_flight.group
                    )
                    q.put_nowait(in_flight.original_msg)

    async def _route_to_dlq(self, topic: str, msg: Message, reason: str = "") -> None:
        dlq_topic = f"{topic}{self.dlq_suffix}"
        headers = dict(msg.headers)
        headers["_dlq_reason"] = reason
        headers["_dlq_original_topic"] = topic
        dlq_msg = msg.model_copy(update={"headers": headers})

        self.dlq[topic].append(dlq_msg)
        self.dlq[dlq_topic].append(dlq_msg)

        self._published_history[dlq_topic].append(dlq_msg)
        for grp in list(self._groups_by_topic[dlq_topic]):
            q = self._group_queues.get((dlq_topic, grp))
            if q is not None:
                q.put_nowait(dlq_msg)

    def get_dlq(self, topic: str) -> list[Message]:
        """
        Returns list of dead-lettered messages for the specified topic.
        """
        return list(self.dlq.get(topic, []))

    async def close(self) -> None:
        """
        Cancels all running visibility timer tasks and cleans up resources.
        """
        async with self._lock:
            for item in list(self._in_flight.values()):
                if item.timer_task and not item.timer_task.done():
                    item.timer_task.cancel()
            self._in_flight.clear()
            self._delivery_attempts.clear()


class InMemoryLockService:
    """
    In-memory distributed lock service providing mutual exclusion, lease renewal,
    TTL expiration takeover, and strictly monotonic fencing tokens.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._fencing_tokens: dict[str, int] = defaultdict(int)
        self._active: dict[str, _ActiveLease] = {}
        self._token_to_resource: dict[str, str] = {}

    async def acquire(self, resource: str, ttl: float, timeout: float = 0.0) -> Lease:
        """
        Attempts to acquire a lock on the given resource with the specified TTL.
        If timeout is <= 0.0, acquisition is non-blocking.
        """
        start_time = time.monotonic()
        while True:
            async with self._lock:
                now = time.monotonic()
                active = self._active.get(resource)
                if active is not None and now >= active.expires_at:
                    # Previous lease expired; release it for takeover
                    self._token_to_resource.pop(active.lease.token, None)
                    del self._active[resource]
                    active = None

                if active is None:
                    self._fencing_tokens[resource] += 1
                    fence = self._fencing_tokens[resource]
                    token = uuid.uuid4().hex
                    lease = Lease(token=token, fence=fence)
                    self._active[resource] = _ActiveLease(
                        lease=lease,
                        expires_at=now + float(ttl),
                        ttl=float(ttl),
                    )
                    self._token_to_resource[token] = resource
                    return lease

            if timeout <= 0.0:
                raise LockAcquisitionError(
                    f"Lock for resource '{resource}' is currently held"
                )
            if (time.monotonic() - start_time) >= timeout:
                raise LockAcquisitionError(
                    f"Timed out acquiring lock for resource '{resource}'"
                )
            await asyncio.sleep(0.01)

    async def renew(self, lease: Lease) -> None:
        """
        Renews an active lease by extending its expiration window by initial TTL.
        Fails if lease has expired or been overtaken.
        """
        async with self._lock:
            resource = self._token_to_resource.get(lease.token)
            if resource is None:
                raise LockRenewalError(
                    f"Lease {lease.token} not found or has been released/expired"
                )
            active = self._active.get(resource)
            if active is None or active.lease.token != lease.token:
                raise LockRenewalError(
                    f"Lease {lease.token} has been lost or superseded"
                )
            now = time.monotonic()
            if now >= active.expires_at:
                self._token_to_resource.pop(lease.token, None)
                self._active.pop(resource, None)
                raise LockRenewalError(f"Lease {lease.token} has expired")
            active.expires_at = now + active.ttl

    async def release(self, lease: Lease) -> None:
        """
        Releases an active lease. Safe and idempotent if lease is stale or expired.
        """
        async with self._lock:
            resource = self._token_to_resource.pop(lease.token, None)
            if resource is None:
                return  # Safe no-op for stale/expired lease
            active = self._active.get(resource)
            if active is not None and active.lease.token == lease.token:
                del self._active[resource]


class InMemoryBlobStore:
    """
    In-memory blob storage supporting raw binary CRUD, deterministic content addressing,
    and lexicographical key listing.
    """

    def __init__(self) -> None:
        self._storage: dict[str, bytes] = {}
        self._lock = asyncio.Lock()

    async def put(self, key: str, data: bytes, content_addressing: bool = False) -> str:
        """
        Persists raw binary data. If content_addressing=True, derives key deterministically.
        """
        if content_addressing:
            digest = hashlib.sha256(data).hexdigest()
            if key:
                final_key = f"{key.rstrip('/')}/{digest}"
            else:
                final_key = digest
        else:
            final_key = key

        async with self._lock:
            self._storage[final_key] = bytes(data)
        return final_key

    async def get(self, key: str) -> bytes:
        """
        Retrieves raw binary data for key. Raises BlobNotFoundError if not found.
        """
        async with self._lock:
            if key not in self._storage:
                raise BlobNotFoundError(f"Blob with key '{key}' not found")
            return self._storage[key]

    async def delete(self, key: str) -> None:
        """
        Deletes key from storage. Idempotent if key does not exist.
        """
        async with self._lock:
            self._storage.pop(key, None)

    async def list(self, prefix: str) -> AsyncIterator[str]:
        """
        Streams keys matching prefix in lexicographical order.
        """
        async with self._lock:
            matching_keys = sorted([k for k in self._storage if k.startswith(prefix)])
        for k in matching_keys:
            yield k


class InMemorySecretStore:
    """
    In-memory secret storage for credentials.
    """

    def __init__(self, initial_secrets: dict[str, str] | None = None) -> None:
        self._secrets: dict[str, str] = dict(initial_secrets) if initial_secrets else {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> str:
        """
        Retrieves secret string. Raises SecretNotFoundError if not found.
        """
        async with self._lock:
            if key not in self._secrets:
                raise SecretNotFoundError(f"Secret '{key}' not found")
            return self._secrets[key]

    async def set(self, key: str, value: str) -> None:
        """
        Stores secret string.
        """
        async with self._lock:
            self._secrets[key] = value

    async def delete(self, key: str) -> None:
        """
        Deletes secret. Idempotent if key does not exist.
        """
        async with self._lock:
            self._secrets.pop(key, None)


class InMemoryAuditSink:
    """
    In-memory tamper-evident audit sink with strictly monotonic sequence numbers.
    """

    def __init__(self) -> None:
        self._sequence: int = 0
        self._events: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def append(self, event: dict[str, Any]) -> int:
        """
        Appends event to audit log, returning strictly monotonically increasing sequence number.
        """
        async with self._lock:
            self._sequence += 1
            seq = self._sequence
            record = copy.deepcopy(event)
            record["_sequence"] = seq
            self._events.append(record)
            return seq

    def get_events(self) -> list[dict[str, Any]]:
        """
        Returns copy of all recorded audit events.
        """
        return copy.deepcopy(self._events)

    def __len__(self) -> int:
        return len(self._events)


# Aliases conforming to Fake* naming
FakeQueue = InMemoryQueue
FakeLockService = InMemoryLockService
FakeBlobStore = InMemoryBlobStore
FakeSecretStore = InMemorySecretStore
FakeAuditSink = InMemoryAuditSink
