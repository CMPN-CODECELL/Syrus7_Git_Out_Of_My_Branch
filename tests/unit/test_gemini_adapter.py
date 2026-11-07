"""Gemini adapter error handling, with a fake client (never calls Google)."""
from types import SimpleNamespace

import pytest

from domains.copilot.infrastructure.gemini_adapter import GeminiConversation, ModelPool, unavailable_message
from domains.copilot.ports import LLMUnavailableError


class ApiError(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code, self.status, self.message = code, "STATUS", f"HTTP {code}"


class FakeModels:
    """outcomes: a list (any model) or {model: list} per model."""

    def __init__(self, outcomes):
        self.outcomes = outcomes if isinstance(outcomes, dict) else {None: list(outcomes)}
        self.calls = 0
        self.models_called = []

    async def generate_content(self, *, model, **_):
        self.calls += 1
        self.models_called.append(model)
        queue = self.outcomes.get(model, self.outcomes.get(None))
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def no_sleep(_):
    return None


def conversation(outcomes, model="gemini-test"):
    models = FakeModels(outcomes)
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return GeminiConversation(client, model, None, [], sleep=no_sleep), models


def ok_response(text="hi"):
    content = SimpleNamespace(parts=[SimpleNamespace(text=text)])
    return SimpleNamespace(candidates=[SimpleNamespace(content=content)], function_calls=[])


async def test_rate_limit_tells_the_trader_to_wait_and_is_not_retried():
    conv, models = conversation([ApiError(429)])
    with pytest.raises(LLMUnavailableError, match="request limit"):
        await conv._generate()
    assert models.calls == 1


async def test_overloaded_gemini_is_retried_once():
    conv, models = conversation([ApiError(503), ok_response("fine")])
    turn = await conv._generate()
    assert turn.text == "fine" and models.calls == 2


async def test_overloaded_twice_gives_an_honest_error():
    conv, models = conversation([ApiError(503), ApiError(503)])
    with pytest.raises(LLMUnavailableError, match="trouble"):
        await conv._generate()
    assert models.calls == 2


async def test_rate_limited_model_falls_back_and_cools_down():
    now = [0.0]
    pool = ModelPool(["main", "backup"], clock=lambda: now[0])
    models = FakeModels({"main": [ApiError(429), ok_response("main again")], "backup": [ok_response("from backup"), ok_response("still backup")]})
    client = SimpleNamespace(aio=SimpleNamespace(models=models))

    first = GeminiConversation(client, pool, None, [], sleep=no_sleep)
    assert (await first._generate()).text == "from backup"
    second = GeminiConversation(client, pool, None, [], sleep=no_sleep)
    assert (await second._generate()).text == "still backup"          # main is cooling down: not even tried
    assert models.models_called == ["main", "backup", "backup"]

    now[0] = 61.0                                                      # cool-down over: main is preferred again
    third = GeminiConversation(client, pool, None, [], sleep=no_sleep)
    assert (await third._generate()).text == "main again"


async def test_bad_request_does_not_fall_back():
    pool = ModelPool(["main", "backup"])
    conv, models = conversation({"main": [ApiError(400)], "backup": [ok_response()]}, model=pool)
    with pytest.raises(LLMUnavailableError):
        await conv._generate()
    assert models.models_called == ["main"]


async def test_every_model_limited_gives_the_limit_message():
    pool = ModelPool(["main", "backup"])
    conv, _ = conversation({"main": [ApiError(429)], "backup": [ApiError(429)]}, model=pool)
    with pytest.raises(LLMUnavailableError, match="every configured model"):
        await conv._generate()


def test_messages_by_code():
    assert "GEMINI_API_KEY" in unavailable_message(403)
    assert "GEMINI_MODEL" in unavailable_message(404)
    assert unavailable_message(None) == "The language model is unavailable right now."
