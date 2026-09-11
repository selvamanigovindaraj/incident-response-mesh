import os

import pytest
from config.settings import AppSettings
from ports.types import Message

from adapters.registry import AdapterRegistry

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "redis"])
async def test_queue_publish_consume_ack_across_backends(backend: str) -> None:
    settings = AppSettings(
        service_name="test",
        queue={
            "backend": backend,
            "redis_url": REDIS_URL if backend == "redis" else None,
        },
        locks={"backend": "memory"},
    )
    async with AdapterRegistry(settings) as registry:
        queue = registry.get_queue("switch_test")
        msg = Message(payload={"hello": "world"}, idempotency_key=f"switch-{backend}")
        await queue.publish("switch-topic", msg)

        received = await anext(queue.consume("switch-topic", "switch-group"))
        assert received.payload == {"hello": "world"}
        await queue.ack(received)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "redis"])
async def test_lock_acquire_release_across_backends(backend: str) -> None:
    settings = AppSettings(
        service_name="test",
        queue={"backend": "memory"},
        locks={
            "backend": backend,
            "redis_url": REDIS_URL if backend == "redis" else None,
        },
    )
    async with AdapterRegistry(settings) as registry:
        lock_service = registry.get_lock_service("switch_test")
        lease = await lock_service.acquire(f"resource-{backend}", ttl=5.0)
        assert lease.fence >= 1
        await lock_service.release(lease)
