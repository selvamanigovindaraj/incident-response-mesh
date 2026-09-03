"""
Certification test suite for in-memory fakes against all ports contract suites.

Demonstrates the standard contract verification pattern:
1. Import contract suites via wildcard imports.
2. Define pytest fixtures providing fake implementations conforming to ports.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from ports.interfaces import AuditSink, BlobStore, LockService, Queue, SecretStore
from ports_testing.contracts.lock import *
from ports_testing.contracts.queue import *
from ports_testing.contracts.stores import *
from ports_testing.fakes import (
    InMemoryAuditSink,
    InMemoryBlobStore,
    InMemoryLockService,
    InMemoryQueue,
    InMemorySecretStore,
)


@pytest_asyncio.fixture
async def queue_adapter(queue_config: QueueConfig) -> AsyncIterator[Queue]:
    """
    Provides an InMemoryQueue instance configured via queue_config for queue contract tests,
    ensuring background tasks are closed upon test teardown.
    """
    queue = InMemoryQueue(
        visibility_timeout=queue_config.visibility_timeout,
        max_retries=queue_config.max_retries,
        dedup_window=queue_config.dedup_window,
        dlq_suffix=queue_config.dlq_suffix,
    )
    try:
        yield queue
    finally:
        await queue.close()


@pytest.fixture
def lock_service() -> LockService:
    """Provides an InMemoryLockService instance for lock contract tests."""
    return InMemoryLockService()


@pytest.fixture
def blob_store() -> BlobStore:
    """Provides an InMemoryBlobStore instance for blob store contract tests."""
    return InMemoryBlobStore()


@pytest.fixture
def secret_store(secret_store_config: SecretStoreConfig) -> SecretStore:
    """
    Provides an InMemorySecretStore instance seeded with the known secret
    from the secret_store_config fixture.
    """
    return InMemorySecretStore(
        {secret_store_config.known_key: secret_store_config.known_value}
    )


@pytest.fixture
def audit_sink() -> AuditSink:
    """Provides an InMemoryAuditSink instance for audit sink contract tests."""
    return InMemoryAuditSink()
