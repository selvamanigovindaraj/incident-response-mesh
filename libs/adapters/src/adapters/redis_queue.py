import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ports.interfaces import Queue
from ports.types import Message
from redis.asyncio import Redis


class RedisStreamQueue(Queue):
    def __init__(
        self,
        redis_client: Redis,
        dedup_window: float = 0.5,
        visibility_timeout: float = 0.2,
        max_deliveries: int = 3,  # max_retries = 2 means max_deliveries = 3
        dlq_suffix: str = ".dlq",
    ) -> None:
        self._redis = redis_client
        self._dedup_window = dedup_window
        self._visibility_timeout = int(visibility_timeout * 1000)
        self._max_deliveries = max_deliveries
        self._dlq_suffix = dlq_suffix

    def _serialize_message(self, msg: Message) -> dict[str, str]:
        msg_dict = msg.model_dump()
        headers = {
            k: v for k, v in msg_dict["headers"].items() if not k.startswith("_redis_")
        }
        return {
            "payload": json.dumps(msg_dict["payload"]),
            "headers": json.dumps(headers),
            "trace_context": json.dumps(msg_dict["trace_context"]),
            "idempotency_key": str(msg_dict["idempotency_key"]),
            "schema_version": str(msg_dict["schema_version"]),
        }

    async def publish(self, topic: str, msg: Message) -> None:
        dedup_key = f"dedup:{topic}:{msg.idempotency_key}"
        if self._dedup_window > 0:
            is_new = await self._redis.set(
                dedup_key,
                "1",
                nx=True,
                px=int(self._dedup_window * 1000),
            )
            if not is_new:
                return

        fields = self._serialize_message(msg)
        await self._redis.xadd(topic, fields, maxlen=100000, approximate=True)  # type: ignore[arg-type, call-arg]

    async def consume(self, topic: str, group: str) -> AsyncIterator[Message]:
        consumer_name = f"consumer-{uuid.uuid4().hex}"
        try:
            await self._redis.xgroup_create(topic, group, id="0", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                raise

        cursor = "0-0"
        while True:
            # 1. XAUTOCLAIM
            # XAUTOCLAIM <key> <group> <consumer> <min-idle-time> <start> [COUNT count] [JUSTID]
            # Returns: [stream_id, [message], [deleted_ids]]
            try:
                autoclaim_res = await self._redis.xautoclaim(
                    name=topic,
                    groupname=group,
                    consumername=consumer_name,
                    min_idle_time=self._visibility_timeout,
                    start_id=cursor,
                    count=100,
                )

                if isinstance(autoclaim_res, (list, tuple)) and len(autoclaim_res) >= 2:
                    raw_cursor = autoclaim_res[0]
                    next_cursor = (
                        raw_cursor.decode()
                        if isinstance(raw_cursor, bytes)
                        else str(raw_cursor)
                    )
                    cursor = "0-0" if next_cursor == "0-0" else next_cursor

                    claimed_messages = autoclaim_res[1]
                    if claimed_messages:
                        for msg_id, fields_res in claimed_messages:
                            msg_obj = await self._process_delivery(
                                topic, group, msg_id, fields_res
                            )
                            if msg_obj:
                                yield msg_obj
                    if cursor != "0-0" or claimed_messages:
                        continue
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                await asyncio.sleep(0.1)

            # 2. XREADGROUP
            try:
                streams: dict[Any, Any] = {topic: ">"}
                read_res: Any = await self._redis.xreadgroup(
                    groupname=group,
                    consumername=consumer_name,
                    streams=streams,
                    count=1,
                    block=100,  # 100ms
                )

                if read_res:
                    for _stream_name, stream_messages in read_res:
                        for msg_id, fields_res in stream_messages:
                            msg_obj = await self._process_delivery(
                                topic, group, msg_id, fields_res
                            )
                            if msg_obj:
                                yield msg_obj
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                await asyncio.sleep(0.1)

    async def _route_to_dlq(
        self,
        topic: str,
        group: str,
        msg_id: str,
        payload: dict[Any, Any] | Message,
    ) -> None:
        if isinstance(payload, Message):
            fields = self._serialize_message(payload)
        else:
            fields = payload
        dlq_topic = f"{topic}{self._dlq_suffix}"
        await self._redis.xadd(dlq_topic, fields, maxlen=100000, approximate=True)  # type: ignore[arg-type, call-arg]
        await self._redis.xack(topic, group, msg_id)
        delivery_key = f"delivery_counts:{topic}:{group}:{msg_id}"
        await self._redis.delete(delivery_key)

    async def _process_delivery(
        self,
        topic: str,
        group: str,
        msg_id: bytes | str,
        fields: dict[Any, Any],
    ) -> Message | None:
        msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)

        # Track delivery
        delivery_key = f"delivery_counts:{topic}:{group}:{msg_id_str}"
        count = await self._redis.hincrby(delivery_key, "count", 1)
        await self._redis.expire(delivery_key, 86400)

        fields_decoded = {
            (k.decode() if isinstance(k, bytes) else k): (
                v.decode() if isinstance(v, bytes) else v
            )
            for k, v in fields.items()
        }

        if count > self._max_deliveries:
            await self._route_to_dlq(topic, group, msg_id_str, fields)
            return None

        # Build Message
        msg = Message(
            payload=json.loads(fields_decoded["payload"]),
            headers=json.loads(fields_decoded.get("headers", "{}")),
            trace_context=json.loads(fields_decoded.get("trace_context", "{}")),
            idempotency_key=fields_decoded["idempotency_key"],
            schema_version=fields_decoded.get("schema_version", "1.0"),
        )
        msg.headers["_redis_msg_id"] = msg_id_str
        msg.headers["_redis_topic"] = topic
        msg.headers["_redis_group"] = group
        return msg

    async def ack(self, msg: Message) -> None:
        msg_id = msg.headers.get("_redis_msg_id")
        topic = msg.headers.get("_redis_topic")
        group = msg.headers.get("_redis_group")
        if not msg_id or not topic or not group:
            return

        await self._redis.xack(topic, group, msg_id)
        delivery_key = f"delivery_counts:{topic}:{group}:{msg_id}"
        await self._redis.delete(delivery_key)

    async def nack(self, msg: Message, requeue: bool = True) -> None:
        msg_id = msg.headers.get("_redis_msg_id")
        topic = msg.headers.get("_redis_topic")
        group = msg.headers.get("_redis_group")
        if not msg_id or not topic or not group:
            return

        delivery_key = f"delivery_counts:{topic}:{group}:{msg_id}"

        if requeue:
            count = await self._redis.hget(delivery_key, "count")
            if count and int(count) >= self._max_deliveries:
                # Max retries reached, route to DLQ
                pass
            else:
                # No-op, let visibility timeout handle it
                return

        await self._route_to_dlq(topic, group, msg_id, msg)
