"""
File Overview: Redis Streams helper for durable event processing, supporting consumer groups, retries, and dead-letter queues.

All Functions/Classes:
- StreamMessage (dataclass): Encapsulates stream message data and retry metadata.
- DurableEventStream (class): Logic for reliable event publishing and consumption via Redis Streams. Data: Redis Streams -> Application Handlers.

Endpoints/APIs:
- None.

Database Tables:
- None.
"""
import asyncio

import json
import logging
from dataclasses import dataclass
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_RETRY_FIELD = "__retry_count"


@dataclass(slots=True)
class StreamMessage:
    stream: str
    message_id: str
    payload: dict[str, Any]
    retry_count: int = 0


class DurableEventStream:
    """Redis Streams helper with consumer groups, retries, and DLQ support."""

    def __init__(
        self,
        redis_client: aioredis.Redis,
        *,
        max_retries: int = 5,
        maxlen: int = 10000,
    ) -> None:
        self._Redis = redis_client
        self._MaxRetries = max_retries
        self._MaxLen = maxlen

    async def ensure_group(self, stream: str, group: str) -> None:
        try:
            await self._Redis.xgroup_create(stream, group, id="0-0", mkstream=True)
            logger.info("Created stream group %s on %s", group, stream)
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def publish(self, stream: str, payload: dict[str, Any]) -> str:
        fields = {
            "payload": json.dumps(payload, default=str),
            _RETRY_FIELD: "0",
        }
        return await self._Redis.xadd(stream, fields, maxlen=self._MaxLen, approximate=True)

    async def read_group(
        self,
        *,
        group: str,
        consumer: str,
        streams: list[str],
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[StreamMessage]:
        response = await self._Redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">" for stream in streams},
            count=count,
            block=block_ms,
        )
        return self._normalize_xreadgroup(response)

    async def claim_stale(
        self,
        *,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int,
        count: int = 10,
    ) -> list[StreamMessage]:
        claimed = await self._Redis.xautoclaim(
            name=stream,
            groupname=group,
            consumername=consumer,
            min_idle_time=min_idle_ms,
            start_id="0-0",
            count=count,
        )
        entries = []
        if isinstance(claimed, (list, tuple)) and len(claimed) >= 2:
            entries = claimed[1]
        return self._normalize_entries(stream, entries)

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        await self._Redis.xack(stream, group, message_id)

    async def retry_or_dead_letter(
        self,
        *,
        stream: str,
        dlq_stream: str,
        group: str,
        message: StreamMessage,
        error: Exception,
    ) -> None:
        next_retry = message.retry_count + 1
        if next_retry > self._MaxRetries:
            dlq_payload = {
                "original_stream": stream,
                "original_message_id": message.message_id,
                "retry_count": next_retry,
                "error": str(error),
                "payload": message.payload,
            }
            await self._Redis.xadd(
                dlq_stream,
                {"payload": json.dumps(dlq_payload, default=str)},
                maxlen=self._MaxLen,
                approximate=True,
            )
            await self.ack(stream, group, message.message_id)
            logger.error(
                "Moved message %s from %s to DLQ=%s after %d retries",
                message.message_id,
                stream,
                dlq_stream,
                next_retry,
            )
            return

        retry_fields = {
            "payload": json.dumps(message.payload, default=str),
            _RETRY_FIELD: str(next_retry),
        }
        await self._Redis.xadd(stream, retry_fields, maxlen=self._MaxLen, approximate=True)
        await self.ack(stream, group, message.message_id)
        logger.warning(
            "Re-queued message %s on %s (retry=%d): %s",
            message.message_id,
            stream,
            next_retry,
            error,
        )
        await asyncio.sleep(0)

    @staticmethod
    def _normalize_xreadgroup(raw: Any) -> list[StreamMessage]:
        messages: list[StreamMessage] = []
        for stream, entries in raw or []:
            stream_name = stream.decode("utf-8") if isinstance(stream, bytes) else str(stream)
            messages.extend(DurableEventStream._normalize_entries(stream_name, entries))
        return messages

    @staticmethod
    def _normalize_entries(stream: str, entries: Any) -> list[StreamMessage]:
        out: list[StreamMessage] = []
        for msg_id, fields in entries or []:
            message_id = msg_id.decode("utf-8") if isinstance(msg_id, bytes) else str(msg_id)
            payload_raw = fields.get(b"payload") if b"payload" in fields else fields.get("payload", "{}")
            retry_raw = fields.get(b"__retry_count") if b"__retry_count" in fields else fields.get("__retry_count", "0")

            if isinstance(payload_raw, bytes):
                payload_raw = payload_raw.decode("utf-8")
            if isinstance(retry_raw, bytes):
                retry_raw = retry_raw.decode("utf-8")

            try:
                payload = json.loads(str(payload_raw))
            except (json.JSONDecodeError, TypeError):
                payload = {}

            try:
                retry_count = int(retry_raw)
            except (TypeError, ValueError):
                retry_count = 0

            out.append(
                StreamMessage(
                    stream=stream,
                    message_id=message_id,
                    payload=payload,
                    retry_count=retry_count,
                )
            )
        return out
