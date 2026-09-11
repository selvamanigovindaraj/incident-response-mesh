from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING, Self

from config.settings import AppSettings
from ports.interfaces import AuditSink, BlobStore, LockService, Queue, SecretStore

from adapters.env_secret_store import EnvSecretStore
from adapters.fs_blob_store import FsBlobStore

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool
    from redis.asyncio import Redis


class AdapterRegistry:
    """Central registry to manage adapter instances and their connection pools."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._redis_client: Redis | None = None
        self._pg_pool: AsyncConnectionPool | None = None

        self._queues: dict[str, Queue] = {}
        self._locks: dict[str, LockService] = {}
        self._blob_stores: dict[str, BlobStore] = {}
        self._audit_sinks: dict[str, AuditSink] = {}
        self._secret_stores: dict[str, SecretStore] = {}

    async def start(self) -> None:
        """Initialize connection pools based on settings."""
        needs_redis = (
            self._settings.queue.backend == "redis"
            or self._settings.locks.backend == "redis"
        )
        if needs_redis:
            from redis.asyncio import Redis

            redis_url = self._settings.queue.redis_url or self._settings.locks.redis_url
            if not redis_url:
                raise RuntimeError(
                    "A redis_url is required when queue.backend or locks.backend is 'redis'"
                )
            self._redis_client = Redis.from_url(redis_url)

        if self._settings.postgres.dsn is not None:
            from psycopg_pool import AsyncConnectionPool

            dsn = await self._settings.postgres.dsn.resolve(self.get_secret_store())
            self._pg_pool = AsyncConnectionPool(dsn, open=False)
            await self._pg_pool.open()

    async def stop(self) -> None:
        """Close connection pools and clear cached instances."""
        try:
            if self._pg_pool:
                try:
                    await self._pg_pool.close()
                finally:
                    self._pg_pool = None
        finally:
            try:
                if self._redis_client:
                    await self._redis_client.aclose()
            finally:
                self._redis_client = None
                self._queues.clear()
                self._locks.clear()
                self._audit_sinks.clear()
                self._blob_stores.clear()
                self._secret_stores.clear()

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.stop()

    def get_queue(self, key: str = "default") -> Queue:
        """Get or instantiate a Queue per settings.queue.backend."""
        if key not in self._queues:
            if self._settings.queue.backend == "memory":
                from ports_testing.fakes import InMemoryQueue

                self._queues[key] = InMemoryQueue()
            else:
                if not self._redis_client:
                    raise RuntimeError("Redis client not initialized")
                from adapters.redis_queue import RedisStreamQueue

                self._queues[key] = RedisStreamQueue(self._redis_client)
        return self._queues[key]

    def get_lock_service(self, key: str = "default") -> LockService:
        """Get or instantiate a LockService per settings.locks.backend."""
        if key not in self._locks:
            if self._settings.locks.backend == "memory":
                from ports_testing.fakes import InMemoryLockService

                self._locks[key] = InMemoryLockService()
            else:
                if not self._redis_client:
                    raise RuntimeError("Redis client not initialized")
                from adapters.redis_lock import RedisLockService

                self._locks[key] = RedisLockService(self._redis_client)
        return self._locks[key]

    def get_blob_store(self, key: str = "default") -> BlobStore:
        """Get or instantiate an FsBlobStore."""
        if key not in self._blob_stores:
            self._blob_stores[key] = FsBlobStore(base_dir=self._settings.blob_store.base_dir)
        return self._blob_stores[key]

    def get_audit_sink(self, key: str = "default") -> AuditSink:
        """Get or instantiate a PgAuditSink."""
        if key not in self._audit_sinks:
            if not self._pg_pool:
                raise RuntimeError("Postgres pool not initialized")
            from adapters.postgres import PgAuditSink

            self._audit_sinks[key] = PgAuditSink(self._pg_pool)
        return self._audit_sinks[key]

    def get_secret_store(self, key: str = "default") -> SecretStore:
        """Get or instantiate an EnvSecretStore."""
        if key not in self._secret_stores:
            self._secret_stores[key] = EnvSecretStore()
        return self._secret_stores[key]
