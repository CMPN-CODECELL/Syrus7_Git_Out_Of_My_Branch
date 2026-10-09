"""Gemini adapter error handling, with a fake client (never calls Google)."""
from types import SimpleNamespace

import pytest

from domains.copilot.infrastructure.gemini_adapter import GeminiConversation, unavailable_message
from domains.copilot.ports import LLMUnavailableError


class ApiError(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code, self.status, self.message = code, "STATUS", f"HTTP {code}"


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def generate_content(self, **_):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def conversation(outcomes):
    models = FakeModels(outcomes)
    client = SimpleNamespace(aio=SimpleNamespace(models=models))

    async def no_sleep(_):
        return None

    return GeminiConversation(client, "gemini-test", None, [], sleep=no_sleep), models


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


def test_messages_by_code():
    assert "GEMINI_API_KEY" in unavailable_message(403)
    assert "GEMINI_MODEL" in unavailable_message(404)
    assert unavailable_message(None) == "The language model is unavailable right now."
