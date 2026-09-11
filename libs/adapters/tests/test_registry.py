import os

import pytest
from config.settings import AppSettings
from ports.interfaces import AuditSink, BlobStore, LockService, Queue, SecretStore

from adapters.registry import AdapterRegistry

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
POSTGRES_DSN = os.environ.get(
    "POSTGRES_DSN", "postgresql://irm_user:irm_password@localhost:5432/irm_db"
)


def _settings(**overrides: object) -> AppSettings:
    base: dict[str, object] = {
        "service_name": "test",
        "queue": {"backend": "redis", "redis_url": REDIS_URL},
        "locks": {"backend": "redis", "redis_url": REDIS_URL},
        "blob_store": {"base_dir": "/tmp/test_blobs"},
    }
    base.update(overrides)
    return AppSettings(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_registry_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_POSTGRES_DSN", POSTGRES_DSN)
    settings = _settings(postgres={"dsn": "TEST_POSTGRES_DSN"})

    async with AdapterRegistry(settings) as registry:
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
    registry = AdapterRegistry(_settings())
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
async def test_registry_memory_backend_needs_no_redis_client() -> None:
    settings = _settings(
        queue={"backend": "memory"}, locks={"backend": "memory"}
    )
    async with AdapterRegistry(settings) as registry:
        queue = registry.get_queue("mem_queue")
        assert isinstance(queue, Queue)
        lock = registry.get_lock_service("mem_lock")
        assert isinstance(lock, LockService)
