"""Per-user live feed: pushes journal updates to the user's open WebSocket connections."""
import logging
from collections import defaultdict
from typing import Any

from shared.contracts.orders import JournalEntry

logger = logging.getLogger(__name__)


def journal_view(entry: JournalEntry) -> dict[str, Any]:
    return {
        "journal_id": str(entry.id),
        "proposal_id": str(entry.proposal_id),
        "action": entry.action,
        "state": entry.state,
        "order_id": entry.order_id,
        "order_status": entry.order_status,
        "filled_qty": entry.filled_qty,
        "avg_fill_price_paise": entry.avg_fill_price,
        "reason": entry.reason,
        "sent_at": entry.sent_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
        "payload": entry.payload.to_request_json(),
        "card": entry.display.model_dump(mode="json") if entry.display else None,
    }


class UserHub:
    def __init__(self) -> None:
        self._sockets: dict[str, set] = defaultdict(set)
        self.sent: list[tuple[str, dict]] = []  # recent pushes, for tests and debugging (bounded)

    def add(self, user_id: str, websocket) -> None:
        self._sockets[user_id].add(websocket)

    def remove(self, user_id: str, websocket) -> None:
        self._sockets[user_id].discard(websocket)

    def connections(self, user_id: str) -> int:
        return len(self._sockets.get(user_id, ()))

    async def publish(self, user_id: str, message: dict[str, Any]) -> None:
        self.sent.append((user_id, message))
        del self.sent[:-200]
        for ws in list(self._sockets.get(user_id, ())):
            try:
                await ws.send_json(message)
            except Exception:
                self._sockets[user_id].discard(ws)

    async def publish_journal(self, entry: JournalEntry) -> None:
        await self.publish(entry.user_id, {"type": "order_update", "order": journal_view(entry)})
