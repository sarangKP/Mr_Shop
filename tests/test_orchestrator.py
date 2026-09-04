"""
Tests for the orchestrator and heuristic resolver.

All methods that call handle_turn or heuristic_resolve are async
(pytest-asyncio asyncio_mode=auto awaits them automatically).
Sync helpers (_new_trace etc.) stay sync.
"""

import pytest
from unittest.mock import patch

from mrshop.memory.session import new_session, get, add_wardrobe_item, set_last_mentioned_item, set_last_suggested_items
from mrshop.classifier.resolver import heuristic_resolve
from mrshop.orchestrator.orchestrator import (
    Orchestrator,
    _new_trace,
    _dispatch_tool,
)
from mrshop.config import get_resolver_and_reply


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_orchestrator(state=None):
    if state is None:
        state = new_session()
    resolver, reply_fn = get_resolver_and_reply()
    return Orchestrator(resolve_reference=resolver, generate_reply=reply_fn, state=state), state


# ---------------------------------------------------------------------------
# heuristic_resolve — in isolation (async because the function is now async)
# ---------------------------------------------------------------------------

class TestHeuristicResolve:
    async def test_finds_exact_wardrobe_item(self):
        state = new_session()
        add_wardrobe_item(state, "navy blazer")
        item, source = await heuristic_resolve("can I buy my navy blazer?", state)
        assert item == "navy blazer"
        assert source == "explicit"

    async def test_extracts_adjective_plus_noun(self):
        state = new_session()
        item, source = await heuristic_resolve("I just got a white shirt", state)
        assert item == "white shirt"
        assert source == "explicit"

    async def test_extracts_bare_clothing_noun(self):
        state = new_session()
        item, source = await heuristic_resolve("I want to buy some jeans", state)
        assert item == "jeans"
        assert source == "explicit"

    async def test_falls_back_to_last_mentioned_item(self):
        state = new_session()
        set_last_mentioned_item(state, "navy blazer")
        item, source = await heuristic_resolve("can I buy it?", state)
        assert item == "navy blazer"
        assert source == "heuristic:last_mentioned"

    async def test_returns_none_when_nothing_found(self):
        state = new_session()
        item, source = await heuristic_resolve("I need some help", state)
        assert item is None
        assert source == "none"

    async def test_wardrobe_match_beats_regex(self):
        state = new_session()
        add_wardrobe_item(state, "navy blazer")
        item, source = await heuristic_resolve("what goes with my navy blazer?", state)
        assert item == "navy blazer"
        assert source == "explicit"

    async def test_bulk_pronoun_resolves_to_first_suggested_item(self):
        state = new_session()
        set_last_mentioned_item(state, "blue shoes")
        set_last_suggested_items(state, ["white shirt", "trousers"])
        item, source = await heuristic_resolve("i want to purchase those items", state)
        assert item == "white shirt"
        assert source == "heuristic:suggested"

    async def test_bulk_pronoun_falls_back_to_last_mentioned_when_no_suggestions(self):
        state = new_session()
        set_last_mentioned_item(state, "navy blazer")
        item, source = await heuristic_resolve("i want to buy those", state)
        assert item == "navy blazer"
        assert source == "heuristic:last_mentioned"


# ---------------------------------------------------------------------------
# _new_trace — schema contract (sync, no orchestrator call)
# ---------------------------------------------------------------------------

def test_new_trace_has_all_required_keys():
    trace = _new_trace(1)
    required = {"turn_id", "stage", "intent_source", "confidence",
                "resolver_source", "tools_invoked", "topic_switch", "latency_ms"}
    assert required == set(trace.keys())

def test_new_trace_initial_values():
    trace = _new_trace(42)
    assert trace["turn_id"] == 42
    assert trace["stage"] == "RECEIVED"
    assert trace["intent_source"] is None
    assert trace["confidence"] is None
    assert trace["tools_invoked"] == []
    assert trace["topic_switch"] is False
    assert trace["latency_ms"] == {}


# ---------------------------------------------------------------------------
# handle_turn — Tier 1 hit paths
# ---------------------------------------------------------------------------

class TestHandleTurnTier1:
    async def test_wardrobe_upload_adds_item(self):
        orch, state = make_orchestrator()
        reply, trace = await orch.handle_turn("I just got a navy blazer")
        assert "navy blazer" in get(state, "wardrobe_items")
        assert trace["intent_source"] == "rule"
        assert "wardrobe_upload" in trace["tools_invoked"]

    async def test_wardrobe_upload_reply_confirms_item(self):
        orch, state = make_orchestrator()
        reply, _ = await orch.handle_turn("I just got a navy blazer")
        assert "navy blazer" in reply

    async def test_purchase_initiates_purchase(self):
        orch, state = make_orchestrator()
        add_wardrobe_item(state, "navy blazer")
        set_last_mentioned_item(state, "navy blazer")
        reply, trace = await orch.handle_turn("I want to buy that jacket")
        assert "purchase" in trace["tools_invoked"]
        assert "$" in reply

    async def test_styling_advice_returns_suggestions(self):
        orch, state = make_orchestrator()
        reply, trace = await orch.handle_turn("what goes with dark blue jeans?")
        assert "styling_advice" in trace["tools_invoked"]
        assert "1." in reply

    async def test_booking_confirms_slot(self):
        orch, state = make_orchestrator()
        reply, trace = await orch.handle_turn("book me a stylist call Friday")
        assert "booking" in trace["tools_invoked"]
        assert "Friday" in reply
        assert "MRSHOP-" in reply


# ---------------------------------------------------------------------------
# handle_turn — turn_trace correctness
# ---------------------------------------------------------------------------

class TestTurnTrace:
    async def test_trace_turn_id_increments(self):
        orch, _ = make_orchestrator()
        _, t1 = await orch.handle_turn("I just got a white shirt")
        _, t2 = await orch.handle_turn("what goes with dark jeans?")
        assert t1["turn_id"] == 1
        assert t2["turn_id"] == 2

    async def test_trace_stage_is_done(self):
        orch, _ = make_orchestrator()
        _, trace = await orch.handle_turn("I just got a white shirt")
        assert trace["stage"] == "DONE"

    async def test_trace_has_latency_keys(self):
        orch, _ = make_orchestrator()
        _, trace = await orch.handle_turn("I just got a white shirt")
        assert "tier1_ms" in trace["latency_ms"]
        assert "total_ms" in trace["latency_ms"]

    async def test_trace_confidence_is_1_on_rule_hit(self):
        orch, _ = make_orchestrator()
        _, trace = await orch.handle_turn("what goes with dark jeans?")
        assert trace["confidence"] == 1.0

    async def test_trace_tools_invoked_contains_intent(self):
        orch, _ = make_orchestrator()
        _, trace = await orch.handle_turn("book me a stylist call Friday")
        assert "booking" in trace["tools_invoked"]


# ---------------------------------------------------------------------------
# handle_turn — topic switch and memory carry-over
# ---------------------------------------------------------------------------

class TestTopicSwitch:
    async def test_topic_switch_detected(self):
        orch, _ = make_orchestrator()
        await orch.handle_turn("what goes with dark jeans?")
        _, trace = await orch.handle_turn("I want to buy that jacket")
        assert trace["topic_switch"] is True

    async def test_wardrobe_survives_topic_switch(self):
        orch, state = make_orchestrator()
        await orch.handle_turn("I just got a navy blazer")
        await orch.handle_turn("what goes with dark jeans?")
        await orch.handle_turn("I want to buy it")
        assert "navy blazer" in get(state, "wardrobe_items")

    async def test_topic_history_populated(self):
        orch, state = make_orchestrator()
        await orch.handle_turn("what goes with dark jeans?")
        await orch.handle_turn("I want to buy that jacket")
        assert "styling_advice" in get(state, "topic_history")

    async def test_no_topic_switch_on_same_intent(self):
        orch, _ = make_orchestrator()
        await orch.handle_turn("what goes with dark jeans?")
        _, trace = await orch.handle_turn("what should I wear today?")
        assert trace["topic_switch"] is False


# ---------------------------------------------------------------------------
# handle_turn — heuristic fallback + assumption surfacing
# ---------------------------------------------------------------------------

class TestHeuristicFallback:
    async def test_assumption_in_reply_when_falling_back(self):
        orch, state = make_orchestrator()
        set_last_mentioned_item(state, "navy blazer")
        reply, _ = await orch.handle_turn("I want to buy it")
        assert "assuming" in reply.lower() or "navy blazer" in reply

    async def test_last_mentioned_item_updated_after_explicit_purchase(self):
        orch, state = make_orchestrator()
        await orch.handle_turn("I just got a leather jacket")
        assert get(state, "last_mentioned_item") == "leather jacket"


# ---------------------------------------------------------------------------
# handle_turn — clarifying question path
# ---------------------------------------------------------------------------

class TestClarifyPath:
    async def test_clarify_on_low_confidence(self):
        orch, _ = make_orchestrator()
        with patch("mrshop.orchestrator.orchestrator.tier2.classify", return_value=(None, 0.1)):
            reply, trace = await orch.handle_turn("asdfghjkl zxcvbnm qwerty")
        assert trace["intent_source"] == "clarify"
        assert trace["stage"] == "DONE"
        assert len(trace["tools_invoked"]) == 0
        assert "styling" in reply.lower() or "wardrobe" in reply.lower()

    async def test_clarify_trace_has_no_tool_calls(self):
        orch, _ = make_orchestrator()
        with patch("mrshop.orchestrator.orchestrator.tier2.classify", return_value=(None, 0.05)):
            _, trace = await orch.handle_turn("hmm I dunno")
        assert trace["tools_invoked"] == []
