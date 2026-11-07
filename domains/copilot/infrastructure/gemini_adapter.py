"""
Gemini adapter (google-genai SDK). Manual function calling only: automatic function calling is
disabled so every tool call passes through Kraken's argument validation and audit.

Model fallback: quotas are per model, so when the configured model is rate-limited (429) or
missing (404) the same request goes to the next model in GEMINI_FALLBACK_MODELS, and the limited
model is skipped for a cool-down. Re-sending a request is safe: an LLM call has no side effects
(tools run only after Kraken validates the model's reply).
"""
import asyncio
import logging
import time
from typing import Any, Callable, Optional

from domains.copilot.ports import FunctionCall, LLMTurn, LLMUnavailableError

logger = logging.getLogger(__name__)

RETRYABLE_CODES = {500, 503}   # Gemini overloaded/internal: one quick retry on the same model
RETRY_DELAY_SECONDS = 1.5
FALLBACK_CODES = {429, 404, 500, 503}
COOLDOWN_SECONDS = {429: 60.0, 404: 3600.0, 500: 30.0, 503: 30.0}


class ModelPool:
    """Ordered models plus a shared cool-down, so one 429 moves every later chat to the next model."""

    def __init__(self, models: list[str], *, clock: Callable[[], float] = time.monotonic):
        self.models = [m for i, m in enumerate(models) if m and m not in models[:i]]
        self._until: dict[str, float] = {}
        self._clock = clock

    def order(self, preferred: Optional[str] = None) -> list[str]:
        now = self._clock()
        ready = [m for m in self.models if self._until.get(m, 0.0) <= now]
        cooling = [m for m in self.models if m not in ready]
        ordered = ready + cooling             # all cooling: still try them rather than fail outright
        if preferred in ready:
            ordered.remove(preferred)
            ordered.insert(0, preferred)
        return ordered

    def cool_down(self, model: str, code: int) -> None:
        self._until[model] = self._clock() + COOLDOWN_SECONDS.get(code, 30.0)


def unavailable_message(code: Optional[int]) -> str:
    """What the trader sees when Gemini fails, by HTTP code (google.genai errors carry `.code`)."""
    if code == 429:
        return "The AI hit its Gemini request limit on every configured model. Wait about a minute and try again."
    if code in (401, 403):
        return "The AI key was rejected by Gemini. Check GEMINI_API_KEY on the server."
    if code == 404:
        return "The configured Gemini model was not found. Check GEMINI_MODEL on the server."
    if code is not None and code >= 500:
        return "Gemini is having trouble right now. Try again in a moment."
    return "The language model is unavailable right now."


class GeminiConversation:
    def __init__(self, client: Any, model, config: Any, contents: list, *, sleep=asyncio.sleep):
        self._client = client
        self._pool = model if isinstance(model, ModelPool) else ModelPool([model])
        self._model = self._pool.models[0]     # the model that answered last; preferred for the next call
        self._config = config
        self._contents = contents
        self._sleep = sleep

    async def _call(self, model: str):
        return await self._client.aio.models.generate_content(model=model, contents=self._contents, config=self._config)

    async def _call_with_retry(self, model: str):
        try:
            return await self._call(model)
        except Exception as exc:
            if getattr(exc, "code", None) not in RETRYABLE_CODES:
                raise
            logger.info("Gemini %s returned %s; retrying once", model, getattr(exc, "code", None))
            await self._sleep(RETRY_DELAY_SECONDS)
            return await self._call(model)

    async def _generate(self) -> LLMTurn:
        last: Optional[Exception] = None
        response = None
        for model in self._pool.order(self._model):
            try:
                response = await self._call_with_retry(model)
                if model != self._model:
                    logger.info("Gemini answered with fallback model %s", model)
                self._model = model
                break
            except Exception as exc:
                last = exc
                code = getattr(exc, "code", None)
                logger.warning("Gemini call failed: model=%s %s code=%s status=%s message=%s", model, type(exc).__name__,
                               code, getattr(exc, "status", None), str(getattr(exc, "message", "") or "")[:200])
                if code not in FALLBACK_CODES:
                    break                       # e.g. 400 bad request or 403 bad key: another model won't help
                self._pool.cool_down(model, code)
        if response is None:
            code = getattr(last, "code", None)
            raise LLMUnavailableError(unavailable_message(code if isinstance(code, int) else None), cause=last) from last

        candidate = (response.candidates or [None])[0]
        if candidate is None or candidate.content is None:
            return LLMTurn(text="")
        self._contents.append(candidate.content)
        calls = [
            FunctionCall(name=fc.name or "", args=dict(fc.args or {}), call_id=getattr(fc, "id", None))
            for fc in (response.function_calls or [])
        ]
        text = "".join(part.text for part in (candidate.content.parts or []) if getattr(part, "text", None))
        return LLMTurn(text=text, function_calls=calls)

    async def send_user(self, text: str) -> LLMTurn:
        from google.genai import types

        self._contents.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))
        return await self._generate()

    async def send_tool_results(self, results: list[tuple[FunctionCall, dict]]) -> LLMTurn:
        from google.genai import types

        parts = []
        for call, payload in results:
            part = types.Part.from_function_response(name=call.name, response=payload)
            if call.call_id and part.function_response is not None:
                part.function_response.id = call.call_id
            parts.append(part)
        self._contents.append(types.Content(role="user", parts=parts))
        return await self._generate()


class GeminiLLM:
    def __init__(self, api_key: str, model: str, *, fallbacks: Optional[list[str]] = None, temperature: float = 0.1):
        self._api_key = api_key
        self._pool = ModelPool([model, *(fallbacks or [])])
        self._temperature = temperature
        self._client: Optional[Any] = None

    def _get_client(self) -> Any:
        if not self._api_key:
            raise LLMUnavailableError("GEMINI_API_KEY is not configured on the server.")
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def new_conversation(self, system_prompt: str, tools: list[dict], history: list[tuple[str, str]]) -> GeminiConversation:
        from google.genai import types

        client = self._get_client()
        declarations = [
            types.FunctionDeclaration(name=t["name"], description=t["description"], parameters=t["parameters"])
            for t in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=self._temperature,
        )
        contents = [
            types.Content(role="model" if role == "assistant" else "user", parts=[types.Part.from_text(text=text)])
            for role, text in history
        ]
        return GeminiConversation(client, self._pool, config, contents)
