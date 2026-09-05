import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from ports_testing.contracts.lock import (
    LockConfig,
    test_lock_concurrency_twenty_contenders,  # noqa: F401
    test_lock_fencing_tokens_are_strictly_monotonic,  # noqa: F401
    test_lock_renew_successfully_extends_ttl,  # noqa: F401
    test_lock_stale_lease_release_noop,  # noqa: F401
    test_lock_ttl_expiration_allows_takeover,  # noqa: F401
)
from redis.asyncio import Redis

from adapters.redis_lock import LockError, RedisLockService

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture
def lock_config() -> LockConfig:
    return LockConfig(
        ttl=0.2,
        expected_error=LockError,
    )


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[Redis, None]:
    client: Redis = Redis.from_url(REDIS_URL, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
def lock_service(redis_client: Redis) -> RedisLockService:
    return RedisLockService(redis_client)
