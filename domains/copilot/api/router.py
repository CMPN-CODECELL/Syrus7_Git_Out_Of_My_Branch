"""
Copilot HTTP API (for the chat UI).

POST   /v1/chat            {"message": "..."} -> {"reply", "tools", "data", "llm_available"}
GET    /v1/chat/history    this user's recent exchanges, oldest first (for re-rendering the chat)
DELETE /v1/chat/history    forget this user's conversation (context and saved history)
GET    /v1/copilot/status  broker / socket / instruments / LLM health

Every route needs a verified Supabase token. /v1/chat is rate-limited per user.
Phase 1 is read-only: nothing here can create, approve or send an order.
"""
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.config.settings import get_settings
from domains.copilot.application.chat_service import reply_to_dict
from shared.auth import AuthUser, require_user

router = APIRouter(tags=["Copilot"])


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)


class _SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: float = 60.0) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


_limiter = _SlidingWindowLimiter()


def _runtime(request: Request):
    runtime = getattr(request.app.state, "kraken", None)
    if runtime is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Kraken runtime is not started")
    return runtime


@router.post("/v1/chat")
async def chat(body: ChatRequest, request: Request, user: AuthUser = Depends(require_user)) -> dict:
    settings = get_settings()
    if not _limiter.allow(f"chat:{user.user_id}", settings.ChatRateLimitPerMinute):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many messages; wait a minute.")
    if len(body.message) > settings.ChatMaxMessageChars:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"Message exceeds {settings.ChatMaxMessageChars} characters")
    reply = await _runtime(request).chat.handle(user.user_id, body.message)
    payload = reply_to_dict(reply)
    payload["request_id"] = getattr(request.state, "request_id", None)
    return payload


@router.get("/v1/chat/history")
async def chat_history(request: Request, user: AuthUser = Depends(require_user), limit: int = 30) -> dict:
    chat = _runtime(request).chat
    turns = await chat.recent_turns(user.user_id, max(1, min(limit, 100)))
    return {"turns": turns, "durable": bool(getattr(chat.log, "durable", False))}


@router.delete("/v1/chat/history", status_code=status.HTTP_204_NO_CONTENT)
async def clear_history(request: Request, user: AuthUser = Depends(require_user)) -> None:
    await _runtime(request).chat.clear_history(user.user_id)


@router.get("/v1/copilot/status")
async def copilot_status(request: Request, user: AuthUser = Depends(require_user)) -> dict:
    return _runtime(request).status()
