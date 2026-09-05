import copy
import json
from typing import Any

from ports.interfaces import AuditSink
from psycopg_pool import AsyncConnectionPool


class PgAuditSink(AuditSink):
    """
    PostgreSQL-backed AuditSink implementation.
    """

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def append(self, event: dict[str, Any]) -> int:
        """
        Appends an event payload to the audit log.
        Returns a monotonically increasing sequence number.
        Makes a deep copy of the event before storing to prevent caller mutation from
        affecting the stored data, and serialize to JSON string to ensure consistency.
        """
        # Deep copy to protect against caller mutations before JSON serialization
        event_copy = copy.deepcopy(event)

        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO audit_events (payload) VALUES (%s) RETURNING seq;",
                (json.dumps(event_copy),),
            )
            result = await cur.fetchone()
            if result is None:
                raise RuntimeError("Failed to retrieve sequence number after insert")
            return result[0]

    async def read_events(self) -> list[dict[str, Any]]:
        """
        Helper method for tests to verify events.
        """
        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("SELECT payload FROM audit_events ORDER BY seq ASC;")
            rows = await cur.fetchall()
            # psycopg 3 might return dictionary or strings for jsonb, depending on setup
            # Since we inserted json string, it might come back as dict if column is jsonb and we configured it,
            # but let's parse if it's string.
            events = []
            for row in rows:
                val = row[0]
                if isinstance(val, str):
                    events.append(json.loads(val))
                else:
                    events.append(val)
            return events
