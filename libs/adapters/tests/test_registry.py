import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from ports.interfaces import AuditSink, BlobStore, LockService, Queue, SecretStore

from adapters.fs_blob_store import FsBlobStore
from adapters.registry import AdapterRegistry

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
POSTGRES_DSN = os.environ.get(
    "POSTGRES_DSN", "postgresql://irm_user:irm_password@localhost:5432/irm_db"
)


@pytest.mark.asyncio
async def test_registry_lifecycle() -> None:
    config = {
        "redis": {"url": REDIS_URL},
        "postgres": {"dsn": POSTGRES_DSN},
        "blob_store": {"base_dir": "/tmp/test_blobs"},
    }

    async with AdapterRegistry(config) as registry:
        # Check that we can get each adapter type
        queue = registry.get_queue("test_queue")
        assert isinstance(queue, Queue)

        lock = registry.get_lock_service("test_lock")
        assert isinstance(lock, LockService)

        blob = registry.get_blob_store("test_blob")
        assert isinstance(blob, BlobStore)

        audit = registry.get_audit_sink("test_audit")
        assert isinstance(audit, AuditSink)

        secret = registry.get_secret_store("test_secret")
        assert isinstance(secret, SecretStore)

        # Re-fetching with same key returns identical instance (cached per key)
        assert registry.get_queue("test_queue") is queue
        assert registry.get_lock_service("test_lock") is lock
        assert registry.get_blob_store("test_blob") is blob
        assert registry.get_audit_sink("test_audit") is audit
        assert registry.get_secret_store("test_secret") is secret

        # Different keys return independent adapter instances
        assert registry.get_queue("other_queue") is not queue
        assert registry.get_lock_service("other_lock") is not lock
        assert registry.get_blob_store("other_blob") is not blob
        assert registry.get_audit_sink("other_audit") is not audit
        assert registry.get_secret_store("other_secret") is not secret

    # After stop, accessing queue/lock/audit should raise RuntimeError
    with pytest.raises(RuntimeError, match="Redis client not initialized"):
        registry.get_queue("test_queue")
    with pytest.raises(RuntimeError, match="Redis client not initialized"):
        registry.get_lock_service("test_lock")
    with pytest.raises(RuntimeError, match="Postgres pool not initialized"):
        registry.get_audit_sink("test_audit")


@pytest.mark.asyncio
async def test_registry_uninitialized_access_raises() -> None:
    registry = AdapterRegistry({})
    with pytest.raises(RuntimeError, match="Redis client not initialized"):
        registry.get_queue("default")
    with pytest.raises(RuntimeError, match="Redis client not initialized"):
        registry.get_lock_service("default")
    with pytest.raises(RuntimeError, match="Postgres pool not initialized"):
        registry.get_audit_sink("default")

    # BlobStore and SecretStore work even without redis/postgres initialized
    blob = registry.get_blob_store("default")
    assert isinstance(blob, BlobStore)
    secret = registry.get_secret_store("default")
    assert isinstance(secret, SecretStore)


@pytest.mark.asyncio
async def test_registry_handles_explicit_none_configs() -> None:
    config = {
        "redis": None,
        "postgres": None,
        "blob_store": None,
    }
    registry = AdapterRegistry(config)
    await registry.start()

    # Starting with None configs does not fail
    with pytest.raises(RuntimeError, match="Redis client not initialized"):
        registry.get_queue()
    with pytest.raises(RuntimeError, match="Postgres pool not initialized"):
        registry.get_audit_sink()

    # get_blob_store with None config section falls back to default "/tmp/blobs"
    blob = registry.get_blob_store()
    assert isinstance(blob, FsBlobStore)
    assert blob.base_dir == Path("/tmp/blobs").resolve()

    await registry.stop()


@pytest.mark.asyncio
async def test_registry_stop_teardown_error_protection() -> None:
    registry = AdapterRegistry({})
    fake_pg_pool = MagicMock()
    fake_pg_pool.close = AsyncMock(side_effect=RuntimeError("PG close failure"))
    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()

    registry._pg_pool = fake_pg_pool
    registry._redis_client = fake_redis
    registry._queues["test"] = MagicMock()
    registry._locks["test"] = MagicMock()
    registry._audit_sinks["test"] = MagicMock()

    with pytest.raises(RuntimeError, match="PG close failure"):
        await registry.stop()

    # Ensure redis was still closed despite pg_pool.close() erroring
    fake_redis.aclose.assert_awaited_once()
    # Ensure caches are cleared and pools set to None
    assert registry._pg_pool is None
    assert registry._redis_client is None
    assert len(registry._queues) == 0
    assert len(registry._locks) == 0
    assert len(registry._audit_sinks) == 0
