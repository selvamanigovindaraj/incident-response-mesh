import os
from collections.abc import AsyncGenerator

import pytest_asyncio
from adapters.postgres import PgAuditSink
from psycopg_pool import AsyncConnectionPool

# Use standard postgres env vars if available, else default to docker-compose settings
POSTGRES_DSN = os.environ.get(
    "POSTGRES_DSN", "postgresql://irm_user:irm_password@localhost:5432/irm_db"
)


@pytest_asyncio.fixture
async def pg_pool() -> AsyncGenerator[AsyncConnectionPool, None]:
    async with AsyncConnectionPool(POSTGRES_DSN) as pool:
        yield pool


@pytest_asyncio.fixture
async def audit_sink(
    pg_pool: AsyncConnectionPool,
) -> AsyncGenerator[PgAuditSink, None]:
    # Setup table for each test to ensure isolation
    async with pg_pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DROP TABLE IF EXISTS audit_events;")
            await cur.execute(
                """
                CREATE TABLE audit_events (
                    seq BIGSERIAL PRIMARY KEY,
                    payload JSONB NOT NULL
                );
                """
            )
            # Ensure immutability at DB level (although tests use superuser/owner typically,
            # in a real setup we might revoke update/delete).
            await cur.execute(
                "REVOKE UPDATE, DELETE ON TABLE audit_events FROM public;"
            )
            # Commit explicitly so DDL changes persist across connections in the pool.
        await conn.commit()

    sink = PgAuditSink(pg_pool)
    yield sink

    # Teardown
    async with pg_pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DROP TABLE IF EXISTS audit_events;")
        await conn.commit()
