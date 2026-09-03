"""
Unit tests verifying the implementation and edge cases of in-memory fakes.
"""

from __future__ import annotations

import asyncio
import hashlib
import time

import pytest
from ports.interfaces import AuditSink, BlobStore, LockService, Queue, SecretStore
from ports.types import Lease, Message
from ports_testing.fakes import (
    BlobNotFoundError,
    FakeAuditSink,
    FakeBlobStore,
    FakeLockService,
    FakeQueue,
    FakeSecretStore,
    InMemoryAuditSink,
    InMemoryBlobStore,
    InMemoryLockService,
    InMemoryQueue,
    InMemorySecretStore,
    LockAcquisitionError,
    LockRenewalError,
    SecretNotFoundError,
)


def test_protocol_conformance() -> None:
    assert isinstance(InMemoryQueue(), Queue)
    assert isinstance(InMemoryLockService(), LockService)
    assert isinstance(InMemoryBlobStore(), BlobStore)
    assert isinstance(InMemorySecretStore(), SecretStore)
    assert isinstance(InMemoryAuditSink(), AuditSink)

    # Aliases
    assert isinstance(FakeQueue(), Queue)
    assert isinstance(FakeLockService(), LockService)
    assert isinstance(FakeBlobStore(), BlobStore)
    assert isinstance(FakeSecretStore(), SecretStore)
    assert isinstance(FakeAuditSink(), AuditSink)


# ============================================================================
# Queue Tests
# ============================================================================


@pytest.mark.asyncio
async def test_queue_publish_and_consume() -> None:
    queue = InMemoryQueue(visibility_timeout=5.0)
    try:
        msg = Message(
            payload={"action": "test"},
            idempotency_key="k1",
        )
        await queue.publish("topic-1", msg)

        received: list[Message] = []
        async for item in queue.consume("topic-1", "group-1"):
            received.append(item)
            await queue.ack(item)
            break

        assert len(received) == 1
        assert received[0].payload == {"action": "test"}
        assert received[0].headers.get("_topic") == "topic-1"
        assert received[0].headers.get("_group") == "group-1"
        assert "_receipt_handle" in received[0].headers
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_queue_fanout_across_consumer_groups() -> None:
    queue = InMemoryQueue(visibility_timeout=5.0)
    try:
        msg = Message(payload={"action": "broadcast"}, idempotency_key="k-broadcast")
        await queue.publish("alerts", msg)

        # Consumer group 1
        grp1_msgs: list[Message] = []
        async for m in queue.consume("alerts", "group-alpha"):
            grp1_msgs.append(m)
            await queue.ack(m)
            break

        # Consumer group 2
        grp2_msgs: list[Message] = []
        async for m in queue.consume("alerts", "group-beta"):
            grp2_msgs.append(m)
            await queue.ack(m)
            break

        assert len(grp1_msgs) == 1
        assert len(grp2_msgs) == 1
        assert grp1_msgs[0].payload == {"action": "broadcast"}
        assert grp2_msgs[0].payload == {"action": "broadcast"}
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_queue_load_balance_within_same_group() -> None:
    queue = InMemoryQueue(visibility_timeout=5.0)
    try:
        for i in range(10):
            await queue.publish(
                "jobs",
                Message(payload={"job_id": i}, idempotency_key=f"job-{i}"),
            )

        consumed_worker1: list[int] = []
        consumed_worker2: list[int] = []

        async def worker(consumed: list[int]) -> None:
            async for m in queue.consume("jobs", "workers"):
                consumed.append(m.payload["job_id"])
                await queue.ack(m)

        t1 = asyncio.create_task(worker(consumed_worker1))
        t2 = asyncio.create_task(worker(consumed_worker2))

        start = time.monotonic()
        while len(consumed_worker1) + len(consumed_worker2) < 10 and (time.monotonic() - start) < 5.0:
            await asyncio.sleep(0.02)

        t1.cancel()
        t2.cancel()
        await asyncio.gather(t1, t2, return_exceptions=True)

        total_consumed = consumed_worker1 + consumed_worker2
        assert len(total_consumed) == 10
        # No duplicates
        assert len(set(total_consumed)) == 10
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_queue_idempotency_deduplication() -> None:
    queue = InMemoryQueue(dedup_window=0.5)
    try:
        msg1 = Message(payload={"val": 1}, idempotency_key="same-key")
        msg2 = Message(payload={"val": 2}, idempotency_key="same-key")

        await queue.publish("dedup-topic", msg1)
        await queue.publish("dedup-topic", msg2)  # Should be dropped

        consumed: list[Message] = []
        async for m in queue.consume("dedup-topic", "grp"):
            consumed.append(m)
            await queue.ack(m)
            break

        assert len(consumed) == 1
        assert consumed[0].payload == {"val": 1}

        # Wait for deduplication window to expire
        await asyncio.sleep(0.55)
        msg3 = Message(payload={"val": 3}, idempotency_key="same-key")
        await queue.publish("dedup-topic", msg3)

        async for m in queue.consume("dedup-topic", "grp"):
            consumed.append(m)
            await queue.ack(m)
            break

        assert len(consumed) == 2
        assert consumed[1].payload == {"val": 3}
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_queue_nack_requeue() -> None:
    queue = InMemoryQueue(visibility_timeout=5.0, max_retries=3)
    try:
        msg = Message(payload={"attempt": 1}, idempotency_key="k-nack")
        await queue.publish("retry-topic", msg)

        iterator = queue.consume("retry-topic", "grp")
        first = await anext(iterator)
        assert first.payload == {"attempt": 1}

        # Nack with requeue=True
        await queue.nack(first, requeue=True)

        second = await anext(iterator)
        assert second.idempotency_key == "k-nack"
        await queue.ack(second)
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_queue_visibility_timeout_redelivery() -> None:
    queue = InMemoryQueue(visibility_timeout=0.08, max_retries=3)
    try:
        msg = Message(payload={"data": "timed"}, idempotency_key="k-vis")
        await queue.publish("vis-topic", msg)

        iterator = queue.consume("vis-topic", "grp")
        first = await anext(iterator)
        assert first.payload == {"data": "timed"}
        # Do not ack; wait for visibility timeout to expire
        await asyncio.sleep(0.12)

        # Should be redelivered
        second = await anext(iterator)
        assert second.idempotency_key == "k-vis"
        await queue.ack(second)
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_queue_dlq_after_n_failures() -> None:
    queue = InMemoryQueue(visibility_timeout=5.0, max_retries=2)
    try:
        msg = Message(payload={"bad": "data"}, idempotency_key="k-bad")
        await queue.publish("dlq-topic", msg)

        iterator = queue.consume("dlq-topic", "grp")
        # Attempt 1 -> failure 1
        m1 = await anext(iterator)
        await queue.nack(m1, requeue=True)

        # Attempt 2 -> failure 2 -> max_retries reached (2), routed to DLQ
        m2 = await anext(iterator)
        await queue.nack(m2, requeue=True)

        # Verify DLQ
        dlq_items = queue.get_dlq("dlq-topic")
        assert len(dlq_items) == 1
        assert dlq_items[0].idempotency_key == "k-bad"
        assert dlq_items[0].headers.get("_dlq_reason") == "nack_max_retries_exceeded"

        # Also verify DLQ topic consumption
        dlq_iter = queue.consume("dlq-topic.dlq", "dlq-grp")
        dlq_delivered = await anext(dlq_iter)
        assert dlq_delivered.idempotency_key == "k-bad"
        await queue.ack(dlq_delivered)
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_queue_nack_without_requeue_routes_immediately_to_dlq() -> None:
    queue = InMemoryQueue(visibility_timeout=5.0, max_retries=10)
    try:
        msg = Message(payload={"toxic": True}, idempotency_key="k-toxic")
        await queue.publish("toxic-topic", msg)

        iterator = queue.consume("toxic-topic", "grp")
        m = await anext(iterator)
        await queue.nack(m, requeue=False)

        dlq_items = queue.get_dlq("toxic-topic")
        assert len(dlq_items) == 1
        assert dlq_items[0].idempotency_key == "k-toxic"
        assert dlq_items[0].headers.get("_dlq_reason") == "nack_without_requeue"
    finally:
        await queue.close()


# ============================================================================
# LockService Tests
# ============================================================================


@pytest.mark.asyncio
async def test_lock_acquire_and_release() -> None:
    lock_service = InMemoryLockService()
    lease = await lock_service.acquire("res-1", ttl=10)
    assert isinstance(lease, Lease)
    assert lease.fence == 1
    assert lease.token

    # Second contender fails while held
    with pytest.raises(LockAcquisitionError):
        await lock_service.acquire("res-1", ttl=10)

    # Release allows acquisition
    await lock_service.release(lease)
    second_lease = await lock_service.acquire("res-1", ttl=10)
    assert second_lease.fence == 2
    await lock_service.release(second_lease)


@pytest.mark.asyncio
async def test_lock_concurrency_twenty_contenders() -> None:
    lock_service = InMemoryLockService()
    results = await asyncio.gather(
        *[lock_service.acquire("res-contended", ttl=10) for _ in range(20)],
        return_exceptions=True,
    )

    leases = [r for r in results if isinstance(r, Lease)]
    errors = [r for r in results if isinstance(r, LockAcquisitionError)]

    # Exactly one acquired, 19 failed
    assert len(leases) == 1
    assert len(errors) == 19
    assert leases[0].fence == 1

    # Cleanup
    await lock_service.release(leases[0])


@pytest.mark.asyncio
async def test_lock_strictly_monotonic_fencing_tokens() -> None:
    lock_service = InMemoryLockService()
    fences: list[int] = []

    for _ in range(5):
        lease = await lock_service.acquire("res-sequence", ttl=10)
        fences.append(lease.fence)
        await lock_service.release(lease)

    assert fences == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_lock_ttl_expiration_and_takeover() -> None:
    lock_service = InMemoryLockService()
    lease1 = await lock_service.acquire("res-expiring", ttl=0.08)
    assert lease1.fence == 1

    # Wait for TTL to expire
    await asyncio.sleep(0.12)

    # New contender takes over
    lease2 = await lock_service.acquire("res-expiring", ttl=10)
    assert lease2.fence == 2

    # Stale release of lease1 does not crash or affect lease2
    await lock_service.release(lease1)

    # lease2 is still valid and held
    with pytest.raises(LockAcquisitionError):
        await lock_service.acquire("res-expiring", ttl=10)

    await lock_service.release(lease2)


@pytest.mark.asyncio
async def test_lock_renew() -> None:
    lock_service = InMemoryLockService()
    lease = await lock_service.acquire("res-renew", ttl=0.15)

    await asyncio.sleep(0.08)
    # Renew before expiration
    await lock_service.renew(lease)

    # Sleep past original 0.15s (0.08 + 0.10 = 0.18s)
    await asyncio.sleep(0.10)

    # Still held!
    with pytest.raises(LockAcquisitionError):
        await lock_service.acquire("res-renew", ttl=10)

    await lock_service.release(lease)


@pytest.mark.asyncio
async def test_lock_renew_fails_on_expired_lease() -> None:
    lock_service = InMemoryLockService()
    lease = await lock_service.acquire("res-renew-fail", ttl=0.05)
    await asyncio.sleep(0.08)

    with pytest.raises(LockRenewalError):
        await lock_service.renew(lease)


@pytest.mark.asyncio
async def test_lock_stale_release_noop() -> None:
    lock_service = InMemoryLockService()
    stale_lease = Lease(token="phantom-token", fence=999)
    # Releasing non-existent lease does not raise
    await lock_service.release(stale_lease)


# ============================================================================
# BlobStore Tests
# ============================================================================


@pytest.mark.asyncio
async def test_blob_store_crud() -> None:
    store = InMemoryBlobStore()
    data = b"hello world blob"
    stored_key = await store.put("folder/item.bin", data)
    assert stored_key == "folder/item.bin"

    retrieved = await store.get("folder/item.bin")
    assert retrieved == data

    await store.delete("folder/item.bin")
    with pytest.raises(BlobNotFoundError):
        await store.get("folder/item.bin")

    # Idempotent delete
    await store.delete("folder/item.bin")


@pytest.mark.asyncio
async def test_blob_store_content_addressing() -> None:
    store = InMemoryBlobStore()
    data = b"deterministic content"
    expected_hash = hashlib.sha256(data).hexdigest()

    key = await store.put("blobs", data, content_addressing=True)
    assert key == f"blobs/{expected_hash}"
    assert await store.get(key) == data


@pytest.mark.asyncio
async def test_blob_store_list_lexicographical() -> None:
    store = InMemoryBlobStore()
    await store.put("data/c.txt", b"c")
    await store.put("data/a.txt", b"a")
    await store.put("data/b.txt", b"b")
    await store.put("other/z.txt", b"z")

    keys: list[str] = []
    async for k in store.list("data/"):
        keys.append(k)

    assert keys == ["data/a.txt", "data/b.txt", "data/c.txt"]


# ============================================================================
# SecretStore Tests
# ============================================================================


@pytest.mark.asyncio
async def test_secret_store() -> None:
    store = InMemorySecretStore({"API_KEY": "secret-val-123"})
    assert await store.get("API_KEY") == "secret-val-123"

    with pytest.raises(SecretNotFoundError):
        await store.get("NONEXISTENT")

    await store.set("NEW_KEY", "abc")
    assert await store.get("NEW_KEY") == "abc"

    await store.delete("NEW_KEY")
    with pytest.raises(SecretNotFoundError):
        await store.get("NEW_KEY")


# ============================================================================
# AuditSink Tests
# ============================================================================


@pytest.mark.asyncio
async def test_audit_sink_monotonic_sequence_and_immutability() -> None:
    sink = InMemoryAuditSink()
    seq1 = await sink.append({"event": "login", "user": "alice"})
    seq2 = await sink.append({"event": "action", "user": "bob"})
    seq3 = await sink.append({"event": "logout", "user": "alice"})

    assert seq1 == 1
    assert seq2 == 2
    assert seq3 == 3

    events = sink.get_events()
    assert len(events) == 3
    assert len(sink) == 3
    assert events[0]["event"] == "login"
    assert events[0]["_sequence"] == 1

    # Immutability verification: mutate the returned event list and original payload
    payload = {"status": "ok"}
    await sink.append(payload)
    payload["status"] = "tampered"

    stored = sink.get_events()[3]
    assert stored["status"] == "ok"
