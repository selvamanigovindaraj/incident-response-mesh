import pytest
from ports.interfaces import AuditSink, BlobStore, LockService, Queue, SecretStore

from adapters.registry import AdapterRegistry


@pytest.mark.asyncio
async def test_registry_lifecycle() -> None:
    config = {
        "redis": {"url": "redis://localhost:6379/0"},
        "postgres": {"dsn": "postgresql://irm_user:irm_password@localhost:5432/irm_db"},
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

        # Re-fetching should return the same instance
        assert registry.get_queue("test_queue") is queue
