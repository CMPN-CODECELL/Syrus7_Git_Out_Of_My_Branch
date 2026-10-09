"""
Chat history: one record per exchange (the trader's message and Kraken's reply), per user.

PgChatLog persists to kraken_chat_turns (scripts/migration_kraken_003_chat.sql), so the
conversation survives page reloads and server restarts. MemoryChatLog is the fallback when the
table is missing (history then lasts until restart) and the test double.

The stored reply is exactly what the UI renders (text, tool traces, tool data, proposal ids).
Order cards are never rebuilt from it: the UI re-reads each proposal from the proposals table.
"""
import itertools
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

MAX_DATA_BYTES = 64_000   # tool data above this (e.g. a long option chain) is dropped from history


@dataclass
class ChatTurn:
    id: int
    message: str
    reply: dict
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "message": self.message, "reply": self.reply, "created_at": self.created_at.isoformat()}


def compact_reply(reply: dict) -> dict:
    """Keep the reply renderable but bounded: oversized tool data is dropped (the text stays)."""
    out = dict(reply)
    try:
        if len(json.dumps(out.get("data") or [], default=str)) > MAX_DATA_BYTES:
            out["data"] = []
            out["data_trimmed"] = True
    except (TypeError, ValueError):
        out["data"] = []
        out["data_trimmed"] = True
    return out


class MemoryChatLog:
    durable = False

    def __init__(self) -> None:
        self._rows: dict[str, list[ChatTurn]] = defaultdict(list)
        self._seq = itertools.count(1)

    async def append(self, user_id: str, message: str, reply: dict) -> None:
        self._rows[user_id].append(ChatTurn(next(self._seq), message, compact_reply(reply), datetime.now(timezone.utc)))

    async def recent(self, user_id: str, limit: int) -> list[ChatTurn]:
        return list(self._rows.get(user_id, [])[-limit:])

    async def clear(self, user_id: str) -> None:
        self._rows.pop(user_id, None)


class PgChatLog:
    durable = True

    def __init__(self, pool) -> None:
        self._pool = pool

    async def append(self, user_id: str, message: str, reply: dict) -> None:
        await self._pool.execute(
            "INSERT INTO kraken_chat_turns (user_id, message, reply) VALUES ($1, $2, $3::jsonb)",
            user_id, message, json.dumps(compact_reply(reply), default=str, separators=(",", ":")),
        )

    async def recent(self, user_id: str, limit: int) -> list[ChatTurn]:
        rows = await self._pool.fetch(
            "SELECT id, message, reply, created_at FROM kraken_chat_turns WHERE user_id = $1 ORDER BY id DESC LIMIT $2",
            user_id, limit,
        )
        turns = []
        for r in reversed(rows):
            reply = r["reply"] if isinstance(r["reply"], dict) else json.loads(r["reply"])
            turns.append(ChatTurn(r["id"], r["message"], reply, r["created_at"]))
        return turns

    async def clear(self, user_id: str) -> None:
        await self._pool.execute("DELETE FROM kraken_chat_turns WHERE user_id = $1", user_id)
