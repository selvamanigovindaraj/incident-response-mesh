import asyncio
import json
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
        max_deliveries: int = 3, # max_retries = 2 means max_deliveries = 3
        dlq_suffix: str = ".dlq"
    ) -> None:
        self._redis = redis_client
        self._dedup_window = dedup_window
        self._visibility_timeout = int(visibility_timeout * 1000)
        self._max_deliveries = max_deliveries
        self._dlq_suffix = dlq_suffix

    async def publish(self, topic: str, msg: Message) -> None:
        dedup_key = f"dedup:{topic}:{msg.idempotency_key}"
        if self._dedup_window > 0:
            is_new = await self._redis.set(
                dedup_key,
                "1",
                nx=True,
                ex=max(1, int(self._dedup_window)) if self._dedup_window >= 1 else None,
                px=int(self._dedup_window * 1000) if self._dedup_window < 1 else None
            )
            if not is_new:
                return

        # Serialize message to dict of strings for Redis Hash
        msg_dict = msg.model_dump()
        fields: dict[str, str | int | bytes] = {
            "payload": json.dumps(msg_dict["payload"]),
            "headers": json.dumps(msg_dict["headers"]),
            "trace_context": json.dumps(msg_dict["trace_context"]),
            "idempotency_key": str(msg_dict["idempotency_key"]),
            "schema_version": str(msg_dict["schema_version"])
        }
        await self._redis.xadd(topic, fields)  # type: ignore

    async def consume(self, topic: str, group: str) -> AsyncIterator[Message]:
        import uuid
        consumer_name = f"consumer-{uuid.uuid4().hex}"
        try:
            await self._redis.xgroup_create(topic, group, id="0", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                raise

        while True:
            # 1. XAUTOCLAIM
            # XAUTOCLAIM <key> <group> <consumer> <min-idle-time> <start> [COUNT count] [JUSTID]
            # Returns: [stream_id, [message], [deleted_ids]]
            try:
                autoclaim_res = await self._redis.xautoclaim(
                    name=topic,
                    groupname=group,
                    consumername="autoclaim_consumer",
                    min_idle_time=self._visibility_timeout,
                    start_id="0-0",
                    count=1
                )
                
                messages = []
                if isinstance(autoclaim_res, (list, tuple)) and len(autoclaim_res) >= 2:
                    messages = autoclaim_res[1]
                
                if messages:
                    msg_id, fields_res = messages[0]
                    msg_obj = await self._process_delivery(topic, group, msg_id, fields_res)
                    if msg_obj:
                        yield msg_obj
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:
                pass # Continue to read group on autoclaim failure

            # 2. XREADGROUP
            try:
                streams: dict[str, str | int | bytes] = {topic: ">"}
                read_res: Any = await self._redis.xreadgroup(  # type: ignore
                    groupname=group,
                    consumername=consumer_name,
                    streams=streams,  # type: ignore
                    count=1,
                    block=100  # 100ms
                )

                if read_res:
                    for stream_name, stream_messages in read_res:
                        if stream_messages:
                            msg_id, fields_res = stream_messages[0]
                            msg_obj = await self._process_delivery(topic, group, msg_id, fields_res)
                            if msg_obj:
                                yield msg_obj
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    async def _process_delivery(self, topic: str, group: str, msg_id: bytes, fields: dict) -> Message | None:
        msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
        
        # Track delivery
        delivery_key = f"delivery_counts:{msg_id_str}"
        count = await self._redis.hincrby(delivery_key, "count", 1)

        fields_decoded = {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in fields.items()
        }

        if count > self._max_deliveries:
            # Route to DLQ
            dlq_topic = f"{topic}{self._dlq_suffix}"
            await self._redis.xadd(dlq_topic, fields)  # type: ignore
            await self._redis.xack(topic, group, msg_id)
            await self._redis.delete(delivery_key)
            return None

        # Build Message
        msg = Message(
            payload=json.loads(fields_decoded["payload"]),
            headers=json.loads(fields_decoded.get("headers", "{}")),
            trace_context=json.loads(fields_decoded.get("trace_context", "{}")),
            idempotency_key=fields_decoded["idempotency_key"],
            schema_version=fields_decoded.get("schema_version", "1.0")
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
        delivery_key = f"delivery_counts:{msg_id}"
        await self._redis.delete(delivery_key)

    async def nack(self, msg: Message, requeue: bool = True) -> None:
        msg_id = msg.headers.get("_redis_msg_id")
        topic = msg.headers.get("_redis_topic")
        group = msg.headers.get("_redis_group")
        if not msg_id or not topic or not group:
            return

        delivery_key = f"delivery_counts:{msg_id}"
        
        if requeue:
            count = await self._redis.hget(delivery_key, "count")
            if count and int(count) >= self._max_deliveries:
                # Max retries reached, route to DLQ
                pass
            else:
                # No-op, let visibility timeout handle it
                return
                
        # Route directly to DLQ
        # We need original fields to push to DLQ. 
        # We can re-serialize the message.
        msg_dict = msg.model_dump()
        # Remove our injected headers before serializing
        headers = dict(msg_dict["headers"])
        headers.pop("_redis_msg_id", None)
        headers.pop("_redis_topic", None)
        headers.pop("_redis_group", None)

        fields: dict[str, str | int | bytes] = {
            "payload": json.dumps(msg_dict["payload"]),
            "headers": json.dumps(headers),
            "trace_context": json.dumps(msg_dict["trace_context"]),
            "idempotency_key": msg_dict["idempotency_key"],
            "schema_version": msg_dict["schema_version"]
        }

        dlq_topic = f"{topic}{self._dlq_suffix}"
        await self._redis.xadd(dlq_topic, fields)  # type: ignore
        await self._redis.xack(topic, group, msg_id)
        await self._redis.delete(delivery_key)

