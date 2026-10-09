"""Chat history: exchanges are saved per user, survive a restart (new service, same log), feed the
LLM context again, and are cleared on request."""
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import jwt

from domains.copilot.application.chat_service import ConversationStore, CopilotChatService
from domains.copilot.infrastructure.chat_log import MAX_DATA_BYTES, ChatTurn, MemoryChatLog, compact_reply
from domains.copilot.ports import FunctionCall, LLMTurn, LLMUnavailableError
from tests.fakes.orders_world import USER, build_world

SECRET = "test-only-jwt-secret-at-least-32-bytes-long!!"


class RecordingLLM:
    def __init__(self, turns):
        self.turns = list(turns)
        self.histories = []

    def new_conversation(self, system_prompt, tools, history):
        self.histories.append(list(history))
        return self

    async def send_user(self, text):
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn

    async def send_tool_results(self, results):
        return self.turns.pop(0)


async def test_exchanges_are_saved_with_what_the_ui_renders():
    w = build_world()
    log = MemoryChatLog()
    llm = RecordingLLM([
        LLMTurn(function_calls=[FunctionCall("draft_order", {"action": "BUY", "symbol_query": "RELIANCE", "quantity": 10})]),
        LLMTurn(text="Card ready. Click Approve to send it."),
    ])
    chat = CopilotChatService(llm, w.toolbox, drafts=w.drafts, log=log)
    reply = await chat.handle(USER, "Buy 10 Reliance at market")
    turns = await chat.recent_turns(USER, 10)
    assert len(turns) == 1 and turns[0]["message"] == "Buy 10 Reliance at market"
    saved = turns[0]["reply"]
    assert saved["reply"] == reply.reply and saved["proposals"] == reply.proposals and saved["tools"][0]["name"] == "draft_order"
    assert await chat.recent_turns("someone-else", 10) == []


async def test_history_survives_restart_and_feeds_context_again():
    w = build_world()
    log = MemoryChatLog()
    first = CopilotChatService(RecordingLLM([LLMTurn(text="Your P&L is up.")]), w.toolbox, log=log)
    await first.handle(USER, "How is my P&L?")

    llm = RecordingLLM([LLMTurn(text="Still up.")])
    restarted = CopilotChatService(llm, w.toolbox, history=ConversationStore(), log=log)
    await restarted.handle(USER, "And now?")
    assert llm.histories[0] == [("user", "How is my P&L?"), ("assistant", "Your P&L is up.")]
    assert [t["message"] for t in await restarted.recent_turns(USER, 10)] == ["How is my P&L?", "And now?"]


async def test_failed_llm_exchange_is_shown_but_not_fed_back_as_context():
    w = build_world()
    log = MemoryChatLog()
    chat = CopilotChatService(RecordingLLM([LLMUnavailableError("The AI hit its Gemini request limit.")]), w.toolbox, log=log)
    await chat.handle(USER, "hello")
    turns = await chat.recent_turns(USER, 10)
    assert turns[0]["reply"]["llm_available"] is False

    llm = RecordingLLM([LLMTurn(text="Hi.")])
    await CopilotChatService(llm, w.toolbox, history=ConversationStore(), log=log).handle(USER, "hello again")
    assert llm.histories[0] == []


async def test_clear_removes_saved_history_and_context():
    w = build_world()
    log = MemoryChatLog()
    llm = RecordingLLM([LLMTurn(text="one"), LLMTurn(text="two")])
    chat = CopilotChatService(llm, w.toolbox, log=log)
    await chat.handle(USER, "first")
    await chat.clear_history(USER)
    assert await chat.recent_turns(USER, 10) == []
    await chat.handle(USER, "second")
    assert llm.histories[1] == []


def test_oversized_tool_data_is_dropped_but_text_kept():
    big = {"reply": "Here is the chain.", "data": [{"tool": "option_chain_near_atm", "result": {"rows": ["x" * (MAX_DATA_BYTES + 1)]}}]}
    out = compact_reply(big)
    assert out["reply"] == "Here is the chain." and out["data"] == [] and out["data_trimmed"] is True


def test_history_endpoint_requires_login_and_returns_only_own_turns(test_client):
    log = MemoryChatLog()
    chat = SimpleNamespace(log=log)

    async def recent_turns(user_id, limit):
        return [t.to_dict() for t in await log.recent(user_id, limit)]

    chat.recent_turns = recent_turns
    original = test_client.app.state.kraken
    test_client.app.state.kraken = SimpleNamespace(chat=chat)
    log._rows[USER].append(ChatTurn(1, "mine", {"reply": "ok"}, datetime.now(timezone.utc)))

    def get(sub):
        token = jwt.encode({"sub": sub, "aud": "authenticated", "exp": int(time.time()) + 600}, SECRET, algorithm="HS256")
        return test_client.get("/v1/chat/history", headers={"Authorization": f"Bearer {token}"})

    try:
        assert test_client.get("/v1/chat/history").status_code == 401
        mine, theirs = get(USER), get("intruder")
        assert mine.status_code == 200 and [t["message"] for t in mine.json()["turns"]] == ["mine"]
        assert theirs.status_code == 200 and theirs.json()["turns"] == [] and theirs.json()["durable"] is False
    finally:
        test_client.app.state.kraken = original
