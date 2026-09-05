import json
from typing import Any

from ports.interfaces import AuditSink
from psycopg_pool import AsyncConnectionPool


class PgAuditSink(AuditSink):
    """PostgreSQL-backed AuditSink implementation.

    Table Schema:
        The sink expects an `audit_events` table managed externally (e.g. via migrations):
        ```sql
        CREATE TABLE audit_events (
            seq BIGSERIAL PRIMARY KEY,
            payload JSONB NOT NULL
        );
        ```

    Immutability Guarantees:
        Immutability is enforced at the database privilege level rather than purely
        in application logic. The DBA must revoke UPDATE and DELETE privileges on the
        `audit_events` table from the application user role:
        ```sql
        REVOKE UPDATE, DELETE ON TABLE audit_events FROM <user>;
        ```
    """

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def append(self, event: dict[str, Any]) -> int:
        """Appends an event payload to the audit log.

        Returns a monotonically increasing sequence number.
        Serializes the event directly to a JSON string to ensure consistency.
        """
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO audit_events (payload) VALUES (%s) RETURNING seq;",
                (json.dumps(event),),
            )
            result = await cur.fetchone()
            if result is None:
                raise RuntimeError("Failed to retrieve sequence number after insert")
            await conn.commit()
            return int(result[0])

    async def read_events(self) -> list[dict[str, Any]]:
        """Read events in sequence order.

        Satisfies the ports_testing async inspection hook/interfaces.
        """
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("SELECT payload FROM audit_events ORDER BY seq ASC;")
            rows = await cur.fetchall()
            # psycopg 3 might return dictionary or strings for jsonb, depending on setup
            # Since we inserted json string, it might come back as dict if column is jsonb and we configured it,
            # but let's parse if it's string.
            events: list[dict[str, Any]] = []
            for row in rows:
                val = row[0]
                if isinstance(val, str):
                    events.append(json.loads(val))
                elif isinstance(val, dict):
                    events.append(val)
                else:
                    events.append(dict(val))
            return events
