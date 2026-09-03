"""
Sabotage tests verifying that contract test suites catch broken implementations (fail-closed design).

Each test deliberately instantiates an adapter that violates a specific contract guarantee,
invokes the corresponding contract test function, and asserts that the contract test
catches the failure by raising AssertionError, pytest.fail.Exception, or TimeoutError.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from ports.types import Lease, Message
from ports_testing.contracts.lock import (
    test_lock_concurrency_twenty_contenders as contract_test_lock_concurrency_twenty_contenders,
)
from ports_testing.contracts.lock import (
    test_lock_fencing_tokens_are_strictly_monotonic as contract_test_lock_fencing_tokens_are_strictly_monotonic,
)
from ports_testing.contracts.queue import (
    QueueConfig,
)
from ports_testing.contracts.queue import (
    test_queue_dlq_routing_after_max_retries as contract_test_queue_dlq_routing_after_max_retries,
)
from ports_testing.contracts.queue import (
    test_queue_idempotency_deduplication as contract_test_queue_idempotency_deduplication,
)
from ports_testing.contracts.queue import (
    test_queue_visibility_timeout_redelivery as contract_test_queue_visibility_timeout_redelivery,
)
from ports_testing.contracts.stores import (
    SecretStoreConfig,
)
from ports_testing.contracts.stores import (
    test_audit_sink_append_returns_monotonically_increasing_sequence as contract_test_audit_sink_append_returns_monotonically_increasing_sequence,
)
from ports_testing.contracts.stores import (
    test_audit_sink_concurrent_appends_have_unique_monotonic_sequences as contract_test_audit_sink_concurrent_appends_have_unique_monotonic_sequences,
)
from ports_testing.contracts.stores import (
    test_audit_sink_payload_immutability_caller_mutation as contract_test_audit_sink_payload_immutability_caller_mutation,
)
from ports_testing.contracts.stores import (
    test_blob_store_content_addressing as contract_test_blob_store_content_addressing,
)
from ports_testing.contracts.stores import (
    test_blob_store_list_prefix_and_lexicographical_ordering as contract_test_blob_store_list_prefix_and_lexicographical_ordering,
)
from ports_testing.contracts.stores import (
    test_secret_store_get_nonexistent_raises as contract_test_secret_store_get_nonexistent_raises,
)
from ports_testing.fakes import (
    InMemoryAuditSink,
    InMemoryBlobStore,
    InMemoryLockService,
    InMemoryQueue,
    InMemorySecretStore,
)

# ============================================================================
# Sabotage Implementations: LockService
# ============================================================================


class BrokenLockStaticFence(InMemoryLockService):
    """Deliberately issues a static/constant fencing token (violates monotonicity)."""

    async def acquire(self, resource: str, ttl: float, timeout: float = 0.0) -> Lease:
        lease = await super().acquire(resource, ttl, timeout)
        return Lease(token=lease.token, fence=1)


class BrokenLockNoMutex(InMemoryLockService):
    """Deliberately grants locks without mutual exclusion (all contenders succeed)."""

    async def acquire(self, resource: str, ttl: float, timeout: float = 0.0) -> Lease:
        return Lease(token=uuid.uuid4().hex, fence=1)


# ============================================================================
# Sabotage Implementations: Queue
# ============================================================================


class BrokenQueueNoDedup(InMemoryQueue):
    """Deliberately bypasses deduplication and publishes duplicate messages."""

    async def publish(self, topic: str, msg: Message) -> None:
        # Intentionally bypass idempotency checks and publish directly
        self._published_history[topic].append(msg)
        for group in list(self._groups_by_topic[topic]):
            q = self._get_or_create_group_queue(topic, group)
            q.put_nowait(msg)


class BrokenQueueNoDLQ(InMemoryQueue):
    """Deliberately fails to route exhausted messages to DLQ; requeues to active queue."""

    async def _route_to_dlq(self, topic: str, msg: Message, reason: str = "") -> None:
        # Instead of DLQ, re-enqueue into active group queue
        for grp in list(self._groups_by_topic[topic]):
            q = self._get_or_create_group_queue(topic, grp)
            q.put_nowait(msg)


class BrokenQueueNoVisibility(InMemoryQueue):
    """Deliberately ignores visibility timeout redelivery; drops expired in-flight messages."""

    async def _visibility_timeout_handler(
        self, receipt_handle: str, timeout: float
    ) -> None:
        await asyncio.sleep(timeout)
        async with self._lock:
            # Drop silently without re-queueing
            self._in_flight.pop(receipt_handle, None)


# ============================================================================
# Sabotage Implementations: AuditSink
# ============================================================================


class BrokenAuditSinkStaticSequence(InMemoryAuditSink):
    """Deliberately returns a static sequence number for all appended events."""

    async def append(self, event: dict[str, Any]) -> int:
        await super().append(event)
        return 1


class BrokenAuditSinkCollidingSequences(InMemoryAuditSink):
    """Deliberately issues colliding sequence numbers under concurrent access."""

    async def append(self, event: dict[str, Any]) -> int:
        await super().append(event)
        return 42


class BrokenAuditSinkMutable(InMemoryAuditSink):
    """Deliberately stores raw mutable references without copying (violates ledger immutability)."""

    async def append(self, event: dict[str, Any]) -> int:
        async with self._lock:
            self._sequence += 1
            seq = self._sequence
            event["_sequence"] = seq
            self._events.append(event)  # Shallow reference: caller can mutate in-place
            return seq


# ============================================================================
# Sabotage Implementations: BlobStore & SecretStore
# ============================================================================


class BrokenBlobStoreNoCAS(InMemoryBlobStore):
    """Deliberately ignores content addressing and returns original key verbatim."""

    async def put(self, key: str, data: bytes, content_addressing: bool = False) -> str:
        async with self._lock:
            self._storage[key] = bytes(data)
        return key


class BrokenBlobStoreUnorderedList(InMemoryBlobStore):
    """Deliberately yields matching keys in reverse order instead of lexicographical order."""

    async def list(self, prefix: str) -> AsyncIterator[str]:
        async with self._lock:
            matching_keys = sorted(
                [k for k in self._storage if k.startswith(prefix)], reverse=True
            )
        for k in matching_keys:
            yield k


class BrokenSecretStoreSilentMiss(InMemorySecretStore):
    """Deliberately returns empty string on nonexistent key instead of raising an Exception."""

    async def get(self, key: str) -> str:
        async with self._lock:
            return self._secrets.get(key, "")


# ============================================================================
# Sabotage Verification Tests
# ============================================================================


@pytest.mark.asyncio
async def test_sabotage_lock_static_fencing_fails_contract() -> None:
    """
    Sabotage: BrokenLockStaticFence issues static fence=1.
    Contract test_lock_fencing_tokens_are_strictly_monotonic must catch and fail.
    """
    broken_lock = BrokenLockStaticFence()
    with pytest.raises(AssertionError) as exc_info:
        await contract_test_lock_fencing_tokens_are_strictly_monotonic(broken_lock)
    assert "strictly monotonically increasing" in str(exc_info.value)


@pytest.mark.asyncio
async def test_sabotage_lock_no_mutex_fails_contract() -> None:
    """
    Sabotage: BrokenLockNoMutex grants locks to all 20 contenders.
    Contract test_lock_concurrency_twenty_contenders must catch and fail.
    """
    broken_lock = BrokenLockNoMutex()
    with pytest.raises(AssertionError) as exc_info:
        await contract_test_lock_concurrency_twenty_contenders(broken_lock)
    assert "Expected exactly 1 contender" in str(exc_info.value)


@pytest.mark.asyncio
async def test_sabotage_queue_no_dedup_fails_contract() -> None:
    """
    Sabotage: BrokenQueueNoDedup delivers duplicate messages with identical idempotency keys.
    Contract test_queue_idempotency_deduplication must catch and fail.
    """
    broken_queue = BrokenQueueNoDedup(dedup_window=0.5)
    queue_config = QueueConfig(dedup_window=0.5, empty_check_timeout=0.05)
    try:
        with pytest.raises((AssertionError, pytest.fail.Exception)) as exc_info:
            await contract_test_queue_idempotency_deduplication(
                broken_queue, queue_config
            )
        assert "Duplicate message was delivered" in str(exc_info.value)
    finally:
        await broken_queue.close()


@pytest.mark.asyncio
async def test_sabotage_queue_no_dlq_fails_contract() -> None:
    """
    Sabotage: BrokenQueueNoDLQ fails to evict messages after max_retries.
    Contract test_queue_dlq_routing_after_max_retries must catch and fail.
    """
    broken_queue = BrokenQueueNoDLQ(max_retries=2)
    queue_config = QueueConfig(max_retries=2, empty_check_timeout=0.05)
    try:
        with pytest.raises((AssertionError, pytest.fail.Exception)) as exc_info:
            await contract_test_queue_dlq_routing_after_max_retries(
                broken_queue, queue_config
            )
        assert "Message was not evicted to DLQ" in str(exc_info.value)
    finally:
        await broken_queue.close()


@pytest.mark.asyncio
async def test_sabotage_queue_no_visibility_redelivery_fails_contract() -> None:
    """
    Sabotage: BrokenQueueNoVisibility drops unacknowledged messages instead of redelivering.
    Contract test_queue_visibility_timeout_redelivery must catch the missing message and fail.
    """
    broken_queue = BrokenQueueNoVisibility(visibility_timeout=0.05)
    queue_config = QueueConfig(visibility_timeout=0.05, redelivery_timeout=0.15)
    try:
        with pytest.raises((AssertionError, pytest.fail.Exception)) as exc_info:
            await contract_test_queue_visibility_timeout_redelivery(
                broken_queue, queue_config
            )
        assert "not redelivered" in str(exc_info.value).lower()
    finally:
        await broken_queue.close()


@pytest.mark.asyncio
async def test_sabotage_audit_sink_static_sequence_fails_contract() -> None:
    """
    Sabotage: BrokenAuditSinkStaticSequence returns constant sequence 1.
    Contract test_audit_sink_append_returns_monotonically_increasing_sequence must catch and fail.
    """
    broken_audit = BrokenAuditSinkStaticSequence()
    with pytest.raises(AssertionError) as exc_info:
        await contract_test_audit_sink_append_returns_monotonically_increasing_sequence(
            broken_audit
        )
    assert "strictly monotonically increasing" in str(exc_info.value)


@pytest.mark.asyncio
async def test_sabotage_audit_sink_colliding_sequences_fails_contract() -> None:
    """
    Sabotage: BrokenAuditSinkCollidingSequences issues duplicate sequence numbers under concurrency.
    Contract test_audit_sink_concurrent_appends_have_unique_monotonic_sequences must catch and fail.
    """
    broken_audit = BrokenAuditSinkCollidingSequences()
    with pytest.raises(AssertionError) as exc_info:
        await (
            contract_test_audit_sink_concurrent_appends_have_unique_monotonic_sequences(
                broken_audit
            )
        )
    assert "Collision detected" in str(exc_info.value)


@pytest.mark.asyncio
async def test_sabotage_audit_sink_caller_mutation_fails_contract() -> None:
    """
    Sabotage: BrokenAuditSinkMutable allows caller to mutate stored ledger events.
    Contract test_audit_sink_payload_immutability_caller_mutation must catch and fail.
    """
    broken_audit = BrokenAuditSinkMutable()
    with pytest.raises(AssertionError) as exc_info:
        await contract_test_audit_sink_payload_immutability_caller_mutation(
            broken_audit
        )
    assert "Audit sink allowed in-place caller mutation" in str(exc_info.value)


@pytest.mark.asyncio
async def test_sabotage_blob_store_no_cas_fails_contract() -> None:
    """
    Sabotage: BrokenBlobStoreNoCAS ignores content-addressing digest derivation.
    Contract test_blob_store_content_addressing must catch and fail.
    """
    broken_blob = BrokenBlobStoreNoCAS()
    with pytest.raises(AssertionError) as exc_info:
        await contract_test_blob_store_content_addressing(broken_blob)
    assert "should incorporate content digest" in str(exc_info.value)


@pytest.mark.asyncio
async def test_sabotage_blob_store_unordered_list_fails_contract() -> None:
    """
    Sabotage: BrokenBlobStoreUnorderedList yields keys in reverse order.
    Contract test_blob_store_list_prefix_and_lexicographical_ordering must catch and fail.
    """
    broken_blob = BrokenBlobStoreUnorderedList()
    with pytest.raises(AssertionError) as exc_info:
        await contract_test_blob_store_list_prefix_and_lexicographical_ordering(
            broken_blob
        )
    assert "Expected lexicographical list" in str(exc_info.value)


@pytest.mark.asyncio
async def test_sabotage_secret_store_silent_miss_fails_contract() -> None:
    """
    Sabotage: BrokenSecretStoreSilentMiss returns empty string on missing key instead of raising.
    Contract test_secret_store_get_nonexistent_raises must catch and fail.
    """
    broken_secret = BrokenSecretStoreSilentMiss()
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        await contract_test_secret_store_get_nonexistent_raises(
            broken_secret, SecretStoreConfig()
        )


class BareAuditSink:
    """Implements only the minimal AuditSink protocol without inspection methods."""

    async def append(self, event: dict[str, Any]) -> int:
        return 1


@pytest.mark.asyncio
async def test_audit_sink_immutability_skips_without_event_inspection() -> None:
    """
    Verifies that test_audit_sink_payload_immutability_caller_mutation skips cleanly
    when the sink adapter does not provide an event inspection / reader method.
    """
    bare_sink = BareAuditSink()
    with pytest.raises(pytest.skip.Exception) as exc_info:
        await contract_test_audit_sink_payload_immutability_caller_mutation(bare_sink)
    assert "No event_reader or inspection method provided" in str(exc_info.value)
