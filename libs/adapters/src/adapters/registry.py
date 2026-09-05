from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self

from ports.interfaces import AuditSink, BlobStore, LockService, Queue, SecretStore
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from adapters.env_secret_store import EnvSecretStore
from adapters.fs_blob_store import FsBlobStore
from adapters.postgres import PgAuditSink
from adapters.redis_lock import RedisLockService
from adapters.redis_queue import RedisStreamQueue


class AdapterRegistry:
    """Central registry to manage adapter instances and their connection pools."""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self._config = config
        self._redis_client: Redis | None = None
        self._pg_pool: AsyncConnectionPool | None = None

        self._queues: dict[str, Queue] = {}
        self._locks: dict[str, LockService] = {}
        self._blob_stores: dict[str, BlobStore] = {}
        self._audit_sinks: dict[str, AuditSink] = {}
        self._secret_stores: dict[str, SecretStore] = {}

    async def start(self) -> None:
        """Initialize connection pools based on config."""
        if "redis" in self._config:
            redis_url = self._config["redis"].get("url", "redis://localhost:6379/0")
            self._redis_client = Redis.from_url(redis_url)

        if "postgres" in self._config:
            pg_dsn = self._config["postgres"].get("dsn")
            if pg_dsn:
                self._pg_pool = AsyncConnectionPool(pg_dsn, open=False)
                await self._pg_pool.open()

    async def stop(self) -> None:
        """Close connection pools."""
        if self._pg_pool:
            await self._pg_pool.close()
            self._pg_pool = None

        if self._redis_client:
            await self._redis_client.aclose()
            self._redis_client = None

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
        """Get or instantiate a RedisStreamQueue."""
        if key not in self._queues:
            if not self._redis_client:
                raise RuntimeError("Redis client not initialized")
            # In a real app we might read queue-specific config from self._config
            # e.g., self._config.get("queues", {}).get(key, {})
            self._queues[key] = RedisStreamQueue(self._redis_client)
        return self._queues[key]

    def get_lock_service(self, key: str = "default") -> LockService:
        """Get or instantiate a RedisLockService."""
        if key not in self._locks:
            if not self._redis_client:
                raise RuntimeError("Redis client not initialized")
            self._locks[key] = RedisLockService(self._redis_client)
        return self._locks[key]

    def get_blob_store(self, key: str = "default") -> BlobStore:
        """Get or instantiate an FsBlobStore."""
        if key not in self._blob_stores:
            base_dir = self._config.get("blob_store", {}).get("base_dir", "/tmp/blobs")
            self._blob_stores[key] = FsBlobStore(base_dir=base_dir)
        return self._blob_stores[key]

    def get_audit_sink(self, key: str = "default") -> AuditSink:
        """Get or instantiate a PgAuditSink."""
        if key not in self._audit_sinks:
            if not self._pg_pool:
                raise RuntimeError("Postgres pool not initialized")
            self._audit_sinks[key] = PgAuditSink(self._pg_pool)
        return self._audit_sinks[key]

    def get_secret_store(self, key: str = "default") -> SecretStore:
        """Get or instantiate an EnvSecretStore."""
        if key not in self._secret_stores:
            self._secret_stores[key] = EnvSecretStore()
        return self._secret_stores[key]
