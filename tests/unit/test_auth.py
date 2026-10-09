"""Supabase JWT verification: signature, expiry, audience and subject are all enforced."""
import time

import jwt
import pytest

from shared.auth.supabase_jwt import AuthError, verify_supabase_jwt

SECRET = "test-only-jwt-secret-at-least-32-bytes-long!!"


def token(**overrides) -> str:
    claims = {"sub": "user-1", "aud": "authenticated", "exp": int(time.time()) + 600, "email": "a@b.c"}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, SECRET, algorithm="HS256")


def test_valid_token():
    user = verify_supabase_jwt(token())
    assert user.user_id == "user-1" and user.email == "a@b.c"


@pytest.mark.parametrize("bad", [
    lambda: token(exp=int(time.time()) - 10),
    lambda: token(aud="anon"),
    lambda: token(sub=None),
    lambda: jwt.encode({"sub": "x", "aud": "authenticated", "exp": int(time.time()) + 60}, "another-secret-that-is-long-enough-123", algorithm="HS256"),
    lambda: jwt.encode({"sub": "x", "aud": "authenticated", "exp": int(time.time()) + 60}, None, algorithm="none"),
    lambda: "not-a-jwt",
    lambda: "",
])
def test_rejects_bad_tokens(bad):
    with pytest.raises(AuthError):
        verify_supabase_jwt(bad())


def test_unsigned_payload_cannot_impersonate(test_client):
    # The old middleware trusted decoded-but-unverified claims; a forged token must now be refused.
    forged = jwt.encode({"sub": "admin", "aud": "authenticated", "exp": int(time.time()) + 60}, None, algorithm="none")
    response = test_client.get("/v1/notifications/alerts", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_chat_requires_login(test_client):
    assert test_client.post("/v1/chat", json={"message": "hi"}).status_code == 401
    assert test_client.get("/v1/copilot/status").status_code == 401


def test_status_with_valid_login(test_client):
    response = test_client.get("/v1/copilot/status", headers={"Authorization": f"Bearer {token()}"})
    assert response.status_code == 200
    body = response.json()
    assert body["broker_configured"] is False and body["llm_configured"] is False


def test_chat_without_llm_key_reports_unavailable(test_client):
    response = test_client.post("/v1/chat", json={"message": "What's my P&L today?"}, headers={"Authorization": f"Bearer {token()}"})
    assert response.status_code == 200
    body = response.json()
    assert body["llm_available"] is False and "GEMINI_API_KEY" in body["reply"]
