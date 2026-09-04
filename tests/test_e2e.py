"""
End-to-end scripted conversation tests (Step 7 / PRD §13).

All test methods that call handle_turn are async (pytest-asyncio
asyncio_mode=auto awaits them automatically).  setup_method stays sync.

The primary scenario is the required topic-switch demo from PRD §13:
  styling advice → purchase, with memory (last_mentioned_item) carrying over.
"""

from unittest.mock import patch

from mrshop.memory.session import new_session, get
from mrshop.orchestrator.orchestrator import Orchestrator
from mrshop.config import get_resolver_and_reply


def make_orch():
    state = new_session()
    resolver, reply_fn = get_resolver_and_reply()
    orch = Orchestrator(resolve_reference=resolver, generate_reply=reply_fn, state=state)
    return orch, state


# ---------------------------------------------------------------------------
# Scenario 1 — required topic-switch demo (styling advice → purchase)
# ---------------------------------------------------------------------------

class TestTopicSwitchScenario:
    def setup_method(self):
        self.orch, self.state = make_orch()

    async def test_turn1_wardrobe_upload(self):
        reply, trace = await self.orch.handle_turn("I just got a navy blazer")
        assert trace["intent_source"] == "rule"
        assert "wardrobe_upload" in trace["tools_invoked"]
        assert "navy blazer" in get(self.state, "wardrobe_items")
        assert get(self.state, "last_mentioned_item") == "navy blazer"

    async def test_turn2_styling_advice_remembers_blazer(self):
        await self.orch.handle_turn("I just got a navy blazer")
        reply, trace = await self.orch.handle_turn("what goes with dark blue jeans?")
        assert trace["intent_source"] == "rule"
        assert "styling_advice" in trace["tools_invoked"]
        assert trace["topic_switch"] is True
        assert "styling_advice" == get(self.state, "current_topic")

    async def test_turn3_purchase_resolves_from_memory(self):
        await self.orch.handle_turn("I just got a navy blazer")
        await self.orch.handle_turn("what goes with dark blue jeans?")
        reply, trace = await self.orch.handle_turn("I want to buy that jacket")
        assert "purchase" in trace["tools_invoked"]
        assert trace["topic_switch"] is True
        assert "cart" in self.state
        assert len(self.state["cart"]) == 1

    async def test_full_scenario_memory_carry_over(self):
        await self.orch.handle_turn("I just got a navy blazer")
        await self.orch.handle_turn("what goes with dark blue jeans?")
        await self.orch.handle_turn("I want to buy that jacket")

        assert "navy blazer" in get(self.state, "wardrobe_items")

        history = get(self.state, "topic_history")
        assert "wardrobe_upload" in history
        assert "styling_advice" in history

        assert get(self.state, "current_topic") == "purchase"

    async def test_full_scenario_reply_mentions_assumption_or_item(self):
        await self.orch.handle_turn("I just got a navy blazer")
        await self.orch.handle_turn("what goes with dark blue jeans?")
        reply, _ = await self.orch.handle_turn("I want to buy that jacket")
        assert "jacket" in reply.lower() or "blazer" in reply.lower() or "assuming" in reply.lower()


# ---------------------------------------------------------------------------
# Scenario 2 — wardrobe → styling → booking (three-intent chain)
# ---------------------------------------------------------------------------

class TestThreeIntentChain:
    def setup_method(self):
        self.orch, self.state = make_orch()

    async def test_three_intent_chain(self):
        r1, t1 = await self.orch.handle_turn("I just got some chelsea boots")
        r2, t2 = await self.orch.handle_turn("what goes with dark blue jeans?")
        r3, t3 = await self.orch.handle_turn("book me a stylist call Friday")

        assert t1["tools_invoked"] == ["wardrobe_upload"]
        assert t2["tools_invoked"] == ["styling_advice"]
        assert t3["tools_invoked"] == ["booking"]

        history = get(self.state, "topic_history")
        assert "wardrobe_upload" in history
        assert "styling_advice" in history
        assert get(self.state, "current_topic") == "booking"

        assert "chelsea boots" in get(self.state, "wardrobe_items")
        assert "Friday" in r3


# ---------------------------------------------------------------------------
# Scenario 3 — clarifying question, then resolved
# ---------------------------------------------------------------------------

class TestClarifyThenResolve:
    def setup_method(self):
        self.orch, self.state = make_orch()

    async def test_clarify_then_clear_intent(self):
        with patch("mrshop.orchestrator.orchestrator.tier2.classify", return_value=(None, 0.1)):
            reply1, trace1 = await self.orch.handle_turn("hmm")

        assert trace1["intent_source"] == "clarify"
        assert trace1["tools_invoked"] == []

        reply2, trace2 = await self.orch.handle_turn("what goes with dark blue jeans?")
        assert trace2["intent_source"] == "rule"
        assert "styling_advice" in trace2["tools_invoked"]


# ---------------------------------------------------------------------------
# Scenario 4 — turn_trace consistency across a multi-turn conversation
# ---------------------------------------------------------------------------

class TestTraceAcrossTurns:
    def setup_method(self):
        self.orch, self.state = make_orch()

    async def test_turn_ids_are_sequential(self):
        _, t1 = await self.orch.handle_turn("I just got a white shirt")
        _, t2 = await self.orch.handle_turn("what goes with dark jeans?")
        _, t3 = await self.orch.handle_turn("I want to buy that jacket")
        assert [t1["turn_id"], t2["turn_id"], t3["turn_id"]] == [1, 2, 3]

    async def test_every_trace_ends_done(self):
        for utterance in [
            "I just got a white shirt",
            "what goes with dark jeans?",
            "book me a stylist call Friday",
        ]:
            _, trace = await self.orch.handle_turn(utterance)
            assert trace["stage"] == "DONE"

    async def test_latency_total_is_non_negative(self):
        _, trace = await self.orch.handle_turn("what goes with dark jeans?")
        assert trace["latency_ms"]["total_ms"] >= 0
