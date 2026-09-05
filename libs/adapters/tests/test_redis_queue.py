import asyncio
import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from ports.types import Message
from ports_testing.contracts.queue import (
    QueueConfig,  # noqa: F401
    queue_config,  # noqa: F401
    test_queue_consumer_group_fanout,  # noqa: F401
    test_queue_dlq_routing_after_max_retries,  # noqa: F401
    test_queue_idempotency_deduplication,  # noqa: F401
    test_queue_nack_redelivery,  # noqa: F401
    test_queue_nack_without_requeue_routes_to_dlq,  # noqa: F401
    test_queue_publish_and_consume,  # noqa: F401
    test_queue_visibility_timeout_redelivery,  # noqa: F401
)
from redis.asyncio import Redis

from adapters.redis_queue import RedisStreamQueue

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[Redis, None]:
    client: Redis = Redis.from_url(REDIS_URL)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
def queue_adapter(redis_client: Redis) -> RedisStreamQueue:
    return RedisStreamQueue(
        redis_client=redis_client,
        dedup_window=0.5,
        visibility_timeout=0.2,
        max_deliveries=2,
        dlq_suffix=".dlq",
    )


@pytest.mark.asyncio
async def test_fractional_dedup_window_px_precision(redis_client: Redis) -> None:
    queue = RedisStreamQueue(redis_client=redis_client, dedup_window=1.5)
    msg = Message(payload={"data": 1}, idempotency_key="dedup-fractional-1")
    await queue.publish("test-dedup-topic", msg)

    # In Redis, the TTL in milliseconds should be approximately 1500ms (> 1000ms)
    pttl = await redis_client.pttl("dedup:test-dedup-topic:dedup-fractional-1")
    assert pttl > 1000, f"Expected pttl > 1000ms for 1.5s window, got {pttl}"
    assert pttl <= 1500


@pytest.mark.asyncio
async def test_delivery_key_scoped_by_topic_and_group(redis_client: Redis) -> None:
    queue = RedisStreamQueue(
        redis_client=redis_client,
        dedup_window=0.5,
        visibility_timeout=0.2,
        max_deliveries=3,
    )
    topic = "scoped-topic"
    msg = Message(payload={"key": "val"}, idempotency_key="scoped-msg-1")
    await queue.publish(topic, msg)

    consumer_a = queue.consume(topic, "group-a")
    delivered_a = await asyncio.wait_for(anext(consumer_a), timeout=2.0)
    msg_id = delivered_a.headers["_redis_msg_id"]

    # Delivery key must be scoped by topic, group, and msg_id
    delivery_key_a = f"delivery_counts:{topic}:group-a:{msg_id}"
    count_a = await redis_client.hget(delivery_key_a, "count")
    assert count_a in (b"1", "1")

    # Delivery key must have a positive TTL
    ttl_a = await redis_client.ttl(delivery_key_a)
    assert 0 < ttl_a <= 86400

    # Independent group-b
    consumer_b = queue.consume(topic, "group-b")
    delivered_b = await asyncio.wait_for(anext(consumer_b), timeout=2.0)
    delivery_key_b = f"delivery_counts:{topic}:group-b:{msg_id}"
    count_b = await redis_client.hget(delivery_key_b, "count")
    assert count_b in (b"1", "1")

    # Acking group A removes group A's delivery key, but leaves group B's delivery key intact
    await queue.ack(delivered_a)
    assert not await redis_client.exists(delivery_key_a)
    assert await redis_client.exists(delivery_key_b)

    await queue.ack(delivered_b)
    assert not await redis_client.exists(delivery_key_b)
