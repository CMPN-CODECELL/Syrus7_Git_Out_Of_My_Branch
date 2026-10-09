"""LLM port: the copilot talks to any provider through this interface (Gemini in production,
a scripted fake in tests)."""
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class FunctionCall:
    name: str
    args: dict
    call_id: Optional[str] = None


@dataclass
class LLMTurn:
    text: str = ""
    function_calls: list[FunctionCall] = field(default_factory=list)


class LLMConversation(Protocol):
    async def send_user(self, text: str) -> LLMTurn: ...

    async def send_tool_results(self, results: list[tuple[FunctionCall, dict]]) -> LLMTurn: ...


class LLMPort(Protocol):
    def new_conversation(self, system_prompt: str, tools: list[dict], history: list[tuple[str, str]]) -> LLMConversation: ...


class LLMUnavailableError(Exception):
    """Provider not configured, quota exhausted, or unreachable."""

    def __init__(self, message: str, *, cause: Any = None):
        super().__init__(message)
        self.cause = cause
