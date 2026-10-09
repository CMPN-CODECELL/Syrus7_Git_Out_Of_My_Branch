"""Chat + draft tools: the LLM can create cards but can never cause a send."""
from domains.copilot.application.chat_service import CopilotChatService
from domains.copilot.ports import FunctionCall, LLMTurn
from tests.fakes.orders_world import USER, build_world


class ScriptedLLM:
    def __init__(self, turns):
        self.turns = list(turns)
        self.payloads = []
        self.tools = None
        self.system = None

    def new_conversation(self, system_prompt, tools, history):
        self.system, self.tools = system_prompt, tools
        return self

    async def send_user(self, text):
        return self.turns.pop(0)

    async def send_tool_results(self, results):
        self.payloads.extend(p for _, p in results)
        return self.turns.pop(0)


class NoSendBroker:
    """Wraps the real client; any order action from the chat path fails the test."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        if name in ("place_order", "modify_order", "cancel_order"):
            raise AssertionError(f"chat path called {name}")
        return getattr(self._inner, name)


async def test_draft_tool_creates_card_and_never_sends():
    w = build_world()
    w.toolbox.s.broker = NoSendBroker(w.client)
    llm = ScriptedLLM([
        LLMTurn(function_calls=[FunctionCall("draft_order", {"action": "BUY", "symbol_query": "RELIANCE", "quantity": 10})]),
        LLMTurn(text="I've prepared a card to buy 10 RELIANCE at market. Click Approve to send it."),
    ])
    chat = CopilotChatService(llm, w.toolbox, drafts=w.drafts)
    reply = await chat.handle(USER, "Buy 10 Reliance at market")
    assert len(reply.proposals) == 1 and w.fake.order_bodies == []
    result = llm.payloads[0]["untrusted_data"]
    assert result["status"] == "proposed" and result["card"]["quantity"] == 10 and "Approve" in result["note"]
    assert {t["name"] for t in llm.tools} >= {"draft_order", "draft_modify_order", "draft_cancel_order"}
    assert "PREPARE" in llm.system
    p = await w.store.get_proposal(__import__("uuid").UUID(reply.proposals[0]))
    assert p.state == "PROPOSED" and p.user_id == USER


async def test_draft_without_quantity_returns_question():
    w = build_world()
    llm = ScriptedLLM([
        LLMTurn(function_calls=[FunctionCall("draft_order", {"action": "BUY", "symbol_query": "RELIANCE"})]),
        LLMTurn(text="How many shares?"),
    ])
    reply = await CopilotChatService(llm, w.toolbox, drafts=w.drafts).handle(USER, "buy reliance")
    assert reply.proposals == [] and llm.payloads[0]["untrusted_data"]["status"] == "needs_clarification"


async def test_draft_tools_absent_when_orders_disabled():
    w = build_world()
    llm = ScriptedLLM([LLMTurn(function_calls=[FunctionCall("draft_order", {"action": "BUY", "symbol_query": "INFY", "quantity": 1})]),
                       LLMTurn(text="Order placement is not enabled.")])
    reply = await CopilotChatService(llm, w.toolbox).handle(USER, "buy 1 infy")
    assert not reply.tools[0].ok and "draft_order" not in {t["name"] for t in llm.tools}
    assert w.fake.order_bodies == [] and reply.proposals == []


async def test_injected_send_instruction_in_args_is_rejected():
    w = build_world()
    llm = ScriptedLLM([
        LLMTurn(function_calls=[FunctionCall("draft_order", {"action": "BUY", "symbol_query": "INFY", "quantity": 1, "approve": True})]),
        LLMTurn(text="ok"),
    ])
    reply = await CopilotChatService(llm, w.toolbox, drafts=w.drafts).handle(USER, "buy")
    assert not reply.tools[0].ok and reply.proposals == []
