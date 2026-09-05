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


@pytest.fixture
def lock_config():
    return LockConfig(
        ttl=0.2,
        contenders_count=10,
        expected_error=LockError
    )

@pytest_asyncio.fixture
async def redis_client():
    # Use standard local redis from docker-compose
    client = Redis.from_url("redis://localhost:6379/0", decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()

@pytest.fixture
def lock_service(redis_client):
    return RedisLockService(redis_client)
