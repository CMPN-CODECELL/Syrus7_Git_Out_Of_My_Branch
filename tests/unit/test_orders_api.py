"""HTTP/WS API for proposals and orders, using an in-memory order world behind the real app."""
import asyncio
import time
from types import SimpleNamespace

import jwt
import pytest

from shared.contracts.orders import OrderDraft
from tests.fakes.orders_world import USER, build_world

SECRET = "test-only-jwt-secret-at-least-32-bytes-long!!"


def token(sub: str = USER) -> str:
    return jwt.encode({"sub": sub, "aud": "authenticated", "exp": int(time.time()) + 600}, SECRET, algorithm="HS256")


def headers(sub: str = USER, **extra) -> dict:
    return {"Authorization": f"Bearer {token(sub)}", "Content-Type": "application/json", **extra}


@pytest.fixture
def api(test_client):
    w = build_world()
    original = test_client.app.state.kraken
    test_client.app.state.kraken = SimpleNamespace(execution=w.execution, proposals=w.proposals, store=w.store, hub=w.hub)
    yield test_client, w
    test_client.app.state.kraken = original


def propose(test_client, w, draft=None):
    async def make():
        return await w.propose(draft or OrderDraft(action="BUY", symbol_query="INFY", quantity=2))
    return test_client.portal.call(make) if hasattr(test_client, "portal") and test_client.portal else asyncio.run(make())


def test_card_then_approve_sends_once(api):
    client, w = api
    p = propose(client, w)
    card = client.get(f"/v1/proposals/{p.id}", headers=headers())
    assert card.status_code == 200 and card.json()["card"]["symbol"] == "INFY" and card.json()["seconds_left"] > 0
    ok = client.post(f"/v1/proposals/{p.id}/approve", json={"payload_hash": p.payload_hash}, headers=headers())
    assert ok.status_code == 200 and ok.json()["status"] == "sent"
    again = client.post(f"/v1/proposals/{p.id}/approve", json={"payload_hash": p.payload_hash}, headers=headers())
    assert again.status_code == 409
    assert w.fake.order_bodies == [p.payload.to_request_json()]
    orders = client.get("/v1/orders", headers=headers()).json()["orders"]
    assert len(orders) == 1 and orders[0]["state"] == "ACKED"


def test_approve_requires_login_json_and_allowed_origin(api):
    client, w = api
    p = propose(client, w)
    body = {"payload_hash": p.payload_hash}
    assert client.post(f"/v1/proposals/{p.id}/approve", json=body).status_code == 401
    form = client.post(f"/v1/proposals/{p.id}/approve", data=body,
                       headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/x-www-form-urlencoded"})
    assert form.status_code == 415
    evil = client.post(f"/v1/proposals/{p.id}/approve", json=body, headers=headers(Origin="https://evil.example"))
    assert evil.status_code == 403
    bad = client.post(f"/v1/proposals/{p.id}/approve", json={"payload_hash": "x"}, headers=headers())
    assert bad.status_code == 422
    assert w.fake.order_bodies == []
    good = client.post(f"/v1/proposals/{p.id}/approve", json=body, headers=headers(Origin="http://localhost:8000"))
    assert good.status_code == 200


def test_other_users_cannot_see_or_approve(api):
    client, w = api
    p = propose(client, w)
    assert client.get(f"/v1/proposals/{p.id}", headers=headers("intruder")).status_code == 404
    r = client.post(f"/v1/proposals/{p.id}/approve", json={"payload_hash": p.payload_hash}, headers=headers("intruder"))
    assert r.status_code == 404 and w.fake.order_bodies == []


def test_reject_closes_the_card(api):
    client, w = api
    p = propose(client, w)
    r = client.post(f"/v1/proposals/{p.id}/reject", json={}, headers=headers())
    assert r.status_code == 200 and r.json()["state"] == "REJECTED"
    assert client.post(f"/v1/proposals/{p.id}/approve", json={"payload_hash": p.payload_hash}, headers=headers()).status_code == 409


def test_stream_requires_auth_and_pushes_updates(api):
    client, w = api
    with client.websocket_connect("/v1/stream/orders") as ws:
        ws.send_json({"type": "auth", "token": "forged"})
        with pytest.raises(Exception):
            ws.receive_json()
    with client.websocket_connect("/v1/stream/orders") as ws:
        ws.send_json({"type": "auth", "token": token()})
        assert ws.receive_json() == {"type": "ready"}
        p = propose(client, w)
        client.post(f"/v1/proposals/{p.id}/approve", json={"payload_hash": p.payload_hash}, headers=headers())
        update = ws.receive_json()
        assert update["type"] == "order_update" and update["order"]["state"] == "ACKED"
