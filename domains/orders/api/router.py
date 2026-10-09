"""
Orders HTTP/WebSocket API (Level 2).

GET  /v1/proposals/{id}            card data, rendered from the stored proposal row
POST /v1/proposals/{id}/approve    {"payload_hash": "..."}: the ONLY route that can send an order
POST /v1/proposals/{id}/reject
GET  /v1/orders                    the user's order journal (polling fallback)
GET  /v1/orders/{journal_id}
WS   /v1/stream/orders             live journal updates; first message {"type":"auth","token":"<jwt>"}

No CSRF token is used: auth is a Bearer header that browsers never attach on their own
(ADR-011). As defence in depth, approve/reject require application/json and, when an Origin
header is present, an allowlisted origin.
"""
import asyncio
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config.settings import get_settings
from domains.orders.application.hub import journal_view
from domains.orders.application.proposals import proposal_view
from shared.auth import AuthError, AuthUser, require_user, verify_supabase_jwt

router = APIRouter(tags=["Orders"])

APPROVE_RATE_PER_MINUTE = 30
WS_AUTH_TIMEOUT_SECONDS = 5.0


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


_hits: dict[str, deque] = defaultdict(deque)


def _rate_ok(key: str, limit: int) -> bool:
    now = time.monotonic()
    hits = _hits[key]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= limit:
        return False
    hits.append(now)
    return True


def _runtime(request_or_ws):
    runtime = getattr(request_or_ws.app.state, "kraken", None)
    if runtime is None or getattr(runtime, "execution", None) is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Order features are not available on this server")
    return runtime


def _origin_allowed(origin: str | None) -> bool:
    return origin is None or origin in get_settings().get_allowed_origins_list()


def _guard_state_change(request: Request) -> None:
    if not _origin_allowed(request.headers.get("origin")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed")
    content_type = request.headers.get("content-type", "")
    if not content_type.split(";")[0].strip().lower() == "application/json":
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Use application/json")


def _parse_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.get("/v1/proposals/{proposal_id}")
async def get_proposal(proposal_id: str, request: Request, user: AuthUser = Depends(require_user)) -> dict:
    proposal = await _runtime(request).proposals.get_for_user(_parse_id(proposal_id), user.user_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    return proposal_view(proposal, datetime.now(timezone.utc))


@router.post("/v1/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str, request: Request, user: AuthUser = Depends(require_user)):
    _guard_state_change(request)  # before reading the body: forms and foreign origins never get parsed
    try:
        body = ApproveRequest.model_validate(await request.json())
    except (ValueError, ValidationError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Body must be {\"payload_hash\": \"<64 hex chars>\"}")
    if not _rate_ok(f"approve:{user.user_id}", APPROVE_RATE_PER_MINUTE):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many approvals; wait a minute.")
    outcome = await _runtime(request).execution.approve(_parse_id(proposal_id), user.user_id, body.payload_hash)
    now = datetime.now(timezone.utc)
    content = {
        "status": outcome.status,
        "message": outcome.message,
        "order": journal_view(outcome.journal) if outcome.journal else None,
        "proposal": proposal_view(outcome.proposal, now) if outcome.proposal else None,
        "new_proposal": proposal_view(outcome.new_proposal, now) if outcome.new_proposal else None,
        "request_id": getattr(request.state, "request_id", None),
    }
    return JSONResponse(status_code=outcome.http_status, content=content)


@router.post("/v1/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str, request: Request, user: AuthUser = Depends(require_user)) -> dict:
    _guard_state_change(request)
    proposal = await _runtime(request).proposals.reject(_parse_id(proposal_id), user.user_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    return proposal_view(proposal, datetime.now(timezone.utc))


@router.get("/v1/orders")
async def list_orders(request: Request, user: AuthUser = Depends(require_user), limit: int = 50) -> dict:
    rows = await _runtime(request).store.list_journal(user.user_id, limit=max(1, min(limit, 200)))
    return {"orders": [journal_view(r) for r in rows]}


@router.get("/v1/orders/{journal_id}")
async def get_order(journal_id: str, request: Request, user: AuthUser = Depends(require_user)) -> dict:
    entry = await _runtime(request).store.get_journal(_parse_id(journal_id))
    if entry is None or entry.user_id != user.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return journal_view(entry)


@router.websocket("/v1/stream/orders")
async def stream_orders(websocket: WebSocket) -> None:
    # Cross-site WebSocket hijacking guard: browsers always send Origin on WS handshakes.
    if not _origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=4403)
        return
    await websocket.accept()
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=WS_AUTH_TIMEOUT_SECONDS)
        if not isinstance(first, dict) or first.get("type") != "auth":
            raise AuthError("first message must be auth")
        user = verify_supabase_jwt(str(first.get("token", "")))
    except (AuthError, asyncio.TimeoutError, ValueError, WebSocketDisconnect):
        await websocket.close(code=4401)
        return
    runtime = getattr(websocket.app.state, "kraken", None)
    hub = getattr(runtime, "hub", None)
    if hub is None:
        await websocket.close(code=4503)
        return
    hub.add(user.user_id, websocket)
    try:
        await websocket.send_json({"type": "ready"})
        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict) and message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        hub.remove(user.user_id, websocket)
