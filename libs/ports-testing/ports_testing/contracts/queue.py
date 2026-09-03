"""
Pytest contract test suite for Queue port implementations.

Downstream adapters should verify conformance by defining `queue_adapter` and
optional `queue_config` fixtures and importing this suite:

    from ports_testing.contracts.queue import *
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any

import pytest
from ports.interfaces import Queue
from ports.types import Message


@dataclass(frozen=True)
class QueueConfig:
    """
    Configuration parameters for tuning queue contract tests.
    """

    visibility_timeout: float = 0.2
    max_retries: int = 2
    dedup_window: float = 0.5
    dlq_suffix: str = ".dlq"
    empty_check_timeout: float = 0.15
    redelivery_timeout: float = 2.0


@pytest.fixture
def queue_config() -> QueueConfig:
    """
    Default queue configuration fixture. Adapters may override this fixture
    to match provider-specific timing thresholds or settings.
    """
    return QueueConfig()


def _get_config(config: Any, key: str, default: Any) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


@pytest.mark.asyncio
async def test_queue_publish_and_consume(
    queue_adapter: Queue, queue_config: Any = None
) -> None:
    """
    Contract: Messages published to a topic are delivered to consumers subscribing
    to that topic with payloads, headers, and idempotency keys preserved.
    """
    topic = "contract-std-delivery"
    group = "contract-std-group"
    payload = {"event": "payment_received", "amount": 100}
    headers = {"x-correlation-id": "corr-123"}
    idempotency_key = "idemp-std-001"

    msg = Message(
        payload=payload,
        headers=headers,
        idempotency_key=idempotency_key,
    )
    await queue_adapter.publish(topic, msg)

    consumer = queue_adapter.consume(topic, group)
    try:
        received = await asyncio.wait_for(anext(consumer), timeout=2.0)
        assert received.payload == payload
        assert received.idempotency_key == idempotency_key
        assert received.headers.get("x-correlation-id") == "corr-123"
        await queue_adapter.ack(received)
    finally:
        if hasattr(consumer, "aclose"):
            await consumer.aclose()


@pytest.mark.asyncio
async def test_queue_nack_redelivery(
    queue_adapter: Queue, queue_config: Any = None
) -> None:
    """
    Contract: When a message is negatively acknowledged with requeue=True,
    it becomes eligible for redelivery and is re-consumed by the consumer group.
    """
    topic = "contract-nack-delivery"
    group = "contract-nack-group"
    msg = Message(
        payload={"action": "transcode"},
        idempotency_key="idemp-nack-001",  # gitleaks:allow
    )
    await queue_adapter.publish(topic, msg)

    consumer = queue_adapter.consume(topic, group)
    try:
        first_delivery = await asyncio.wait_for(anext(consumer), timeout=2.0)
        assert first_delivery.idempotency_key == "idemp-nack-001"  # gitleaks:allow

        # Reject with requeue
        await queue_adapter.nack(first_delivery, requeue=True)

        second_delivery = await asyncio.wait_for(anext(consumer), timeout=2.0)
        assert second_delivery.idempotency_key == "idemp-nack-001"  # gitleaks:allow
        assert second_delivery.payload == {"action": "transcode"}
        await queue_adapter.ack(second_delivery)
    finally:
        if hasattr(consumer, "aclose"):
            await consumer.aclose()


@pytest.mark.asyncio
async def test_queue_visibility_timeout_redelivery(
    queue_adapter: Queue, queue_config: Any = None
) -> None:
    """
    Contract: If a consumed message is neither acknowledged nor negatively acknowledged
    before the visibility timeout expires, it is automatically redelivered.
    """
    vis_timeout = float(_get_config(queue_config, "visibility_timeout", 0.2))
    redelivery_timeout = float(_get_config(queue_config, "redelivery_timeout", 2.0))
    topic = "contract-vis-delivery"
    group = "contract-vis-group"

    msg = Message(
        payload={"action": "heartbeat"},
        idempotency_key="idemp-vis-001",
    )
    await queue_adapter.publish(topic, msg)

    consumer = queue_adapter.consume(topic, group)
    try:
        first_delivery = await asyncio.wait_for(anext(consumer), timeout=2.0)
        assert first_delivery.idempotency_key == "idemp-vis-001"

        # Do not ack/nack; wait for visibility timeout to expire
        await asyncio.sleep(vis_timeout + 0.15)

        # Message must now be redelivered
        try:
            redelivered = await asyncio.wait_for(
                anext(consumer), timeout=redelivery_timeout
            )
        except TimeoutError:
            pytest.fail(
                f"Message was not redelivered after visibility timeout of {vis_timeout}s expired"
            )

        assert redelivered.idempotency_key == "idemp-vis-001"
        assert redelivered.payload == {"action": "heartbeat"}
        await queue_adapter.ack(redelivered)
    finally:
        if hasattr(consumer, "aclose"):
            await consumer.aclose()


@pytest.mark.asyncio
async def test_queue_dlq_routing_after_max_retries(
    queue_adapter: Queue, queue_config: Any = None
) -> None:
    """
    Contract: After exhausting max retry attempts (failures), the unacknowledged
    message is evicted from active consumption and routed to the Dead Letter Queue.
    """
    max_retries = int(_get_config(queue_config, "max_retries", 2))
    dlq_suffix = str(_get_config(queue_config, "dlq_suffix", ".dlq"))
    empty_check_timeout = float(_get_config(queue_config, "empty_check_timeout", 0.15))
    topic = "contract-dlq-delivery"
    dlq_topic = f"{topic}{dlq_suffix}"
    group = "contract-dlq-group"

    msg = Message(
        payload={"malformed": True},
        idempotency_key="idemp-dlq-001",
    )
    await queue_adapter.publish(topic, msg)

    consumer = queue_adapter.consume(topic, group)
    try:
        for _ in range(max_retries):
            delivery = await asyncio.wait_for(anext(consumer), timeout=2.0)
            assert delivery.idempotency_key == "idemp-dlq-001"
            await queue_adapter.nack(delivery, requeue=True)

        # Active queue must now be empty for this message
        try:
            unexpected = await asyncio.wait_for(
                anext(consumer), timeout=empty_check_timeout
            )
            pytest.fail(
                f"Message was not evicted to DLQ after {max_retries} failures: {unexpected}"
            )
        except TimeoutError:
            pass  # Successfully evicted from original queue

        # Verify DLQ topic receives the evicted message
        dlq_consumer = queue_adapter.consume(dlq_topic, "contract-dlq-audit-group")
        try:
            dlq_msg = await asyncio.wait_for(anext(dlq_consumer), timeout=2.0)
            assert dlq_msg.idempotency_key == "idemp-dlq-001"
            await queue_adapter.ack(dlq_msg)
        finally:
            if hasattr(dlq_consumer, "aclose"):
                await dlq_consumer.aclose()

        # If adapter exposes direct DLQ query method, verify it as well
        if hasattr(queue_adapter, "get_dlq") and callable(queue_adapter.get_dlq):
            dlq_list = queue_adapter.get_dlq(topic)
            assert any(m.idempotency_key == "idemp-dlq-001" for m in dlq_list)
    finally:
        if hasattr(consumer, "aclose"):
            await consumer.aclose()


@pytest.mark.asyncio
async def test_queue_nack_without_requeue_routes_to_dlq(
    queue_adapter: Queue, queue_config: Any = None
) -> None:
    """
    Contract: When nack(requeue=False) is called, the message is immediately routed
    to the DLQ without further retries on the main topic.
    """
    dlq_suffix = str(_get_config(queue_config, "dlq_suffix", ".dlq"))
    topic = "contract-nack-dlq"
    dlq_topic = f"{topic}{dlq_suffix}"
    group = "contract-nack-dlq-group"

    msg = Message(
        payload={"immediate_poison": True},
        idempotency_key="idemp-poison-001",
    )
    await queue_adapter.publish(topic, msg)

    consumer = queue_adapter.consume(topic, group)
    try:
        delivery = await asyncio.wait_for(anext(consumer), timeout=2.0)
        assert delivery.idempotency_key == "idemp-poison-001"
        await queue_adapter.nack(delivery, requeue=False)

        # Verify routed to DLQ topic
        dlq_consumer = queue_adapter.consume(dlq_topic, "contract-poison-group")
        try:
            dlq_msg = await asyncio.wait_for(anext(dlq_consumer), timeout=2.0)
            assert dlq_msg.idempotency_key == "idemp-poison-001"
            await queue_adapter.ack(dlq_msg)
        finally:
            if hasattr(dlq_consumer, "aclose"):
                await dlq_consumer.aclose()
    finally:
        if hasattr(consumer, "aclose"):
            await consumer.aclose()


@pytest.mark.asyncio
async def test_queue_idempotency_deduplication(
    queue_adapter: Queue, queue_config: Any = None
) -> None:
    """
    Contract: Duplicate messages published with the same idempotency key within the
    deduplication window are deduplicated, ensuring only a single delivery.
    """
    dedup_window = float(_get_config(queue_config, "dedup_window", 0.5))
    empty_check_timeout = float(_get_config(queue_config, "empty_check_timeout", 0.15))
    topic = "contract-dedup-delivery"
    group = "contract-dedup-group"

    msg1 = Message(payload={"val": "first"}, idempotency_key="idemp-dedup-key")
    msg2 = Message(payload={"val": "second"}, idempotency_key="idemp-dedup-key")

    await queue_adapter.publish(topic, msg1)
    await queue_adapter.publish(topic, msg2)

    consumer = queue_adapter.consume(topic, group)
    pending_next: asyncio.Task[Message] | None = None
    try:
        delivered = await asyncio.wait_for(anext(consumer), timeout=2.0)
        assert delivered.idempotency_key == "idemp-dedup-key"
        assert delivered.payload == {"val": "first"}
        await queue_adapter.ack(delivered)

        # Verify no duplicate message is delivered (reusing consumer iterator)
        async def _fetch_next() -> Message:
            return await anext(consumer)

        pending_next = asyncio.create_task(_fetch_next())
        try:
            unexpected = await asyncio.wait_for(
                asyncio.shield(pending_next), timeout=empty_check_timeout
            )
            pytest.fail(f"Duplicate message was delivered: {unexpected}")
        except TimeoutError:
            pass  # Correctly deduplicated

        # After dedup window passes, message with same key can be published again
        if dedup_window > 0:
            await asyncio.sleep(dedup_window + 0.15)
            msg3 = Message(payload={"val": "third"}, idempotency_key="idemp-dedup-key")
            await queue_adapter.publish(topic, msg3)

            third_delivery = await asyncio.wait_for(pending_next, timeout=2.0)
            assert third_delivery.idempotency_key == "idemp-dedup-key"
            assert third_delivery.payload == {"val": "third"}
            await queue_adapter.ack(third_delivery)
    finally:
        if pending_next is not None and not pending_next.done():
            pending_next.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending_next
        if hasattr(consumer, "aclose"):
            await consumer.aclose()


@pytest.mark.asyncio
async def test_queue_consumer_group_fanout(
    queue_adapter: Queue, queue_config: Any = None
) -> None:
    """
    Contract: Each consumer group subscribed to a topic receives an independent copy
    of published messages (fan-out semantics).
    """
    topic = "contract-fanout-topic"
    msg = Message(payload={"broadcast": True}, idempotency_key="idemp-fanout-001")
    await queue_adapter.publish(topic, msg)

    consumer_alpha = queue_adapter.consume(topic, "group-alpha")
    consumer_beta = queue_adapter.consume(topic, "group-beta")

    try:
        alpha_delivery = await asyncio.wait_for(anext(consumer_alpha), timeout=2.0)
        beta_delivery = await asyncio.wait_for(anext(consumer_beta), timeout=2.0)

        assert alpha_delivery.idempotency_key == "idemp-fanout-001"
        assert beta_delivery.idempotency_key == "idemp-fanout-001"
        assert alpha_delivery.payload == {"broadcast": True}
        assert beta_delivery.payload == {"broadcast": True}

        await queue_adapter.ack(alpha_delivery)
        await queue_adapter.ack(beta_delivery)
    finally:
        if hasattr(consumer_alpha, "aclose"):
            await consumer_alpha.aclose()
        if hasattr(consumer_beta, "aclose"):
            await consumer_beta.aclose()


__all__ = [
    "QueueConfig",
    "queue_config",
    "test_queue_consumer_group_fanout",
    "test_queue_dlq_routing_after_max_retries",
    "test_queue_idempotency_deduplication",
    "test_queue_nack_redelivery",
    "test_queue_nack_without_requeue_routes_to_dlq",
    "test_queue_publish_and_consume",
    "test_queue_visibility_timeout_redelivery",
]
