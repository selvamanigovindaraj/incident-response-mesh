import pytest
import pytest_asyncio
from redis.asyncio import Redis
from adapters.redis_queue import RedisStreamQueue
from ports_testing.contracts.queue import *

@pytest_asyncio.fixture
async def redis_client():
    client = Redis(host="localhost", port=6379, db=0)
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
        dlq_suffix=".dlq"
    )
