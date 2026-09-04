"""
Tests for Step 9: Tier 3 LLM resolver and config bootstrap logic.

All Ollama HTTP calls are mocked — these tests run fully offline.

Groups:
  - llm_resolve: happy path, fallback on HTTP failure, fallback on "none" response
  - config.bootstrap: LLM_ENABLED=true/false/auto + Ollama up/down
  - End-to-end: orchestrator with llm_resolve injected
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mrshop.memory.session import new_session, add_wardrobe_item, set_last_mentioned_item, get
from mrshop.classifier.resolver import llm_resolve, heuristic_resolve, _build_extraction_prompt
from mrshop.generator.reply import llm_reply, template_reply
from mrshop.orchestrator.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import json as _json


def _mock_ollama_response(text: str):
    """Return an AsyncMock httpx client that replies with *text* via client.post (resolver tests)."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": text}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.get = AsyncMock(return_value=mock_resp)
    return mock_client


class _FakeStreamResp:
    """Async context manager that yields JSON chunks simulating Ollama streaming."""

    def __init__(self, text: str):
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        yield _json.dumps({"response": self._text, "done": False})
        yield _json.dumps({"response": "", "done": True})


class _FailStreamCtx:
    """Async context manager that raises ConnectError on enter."""

    async def __aenter__(self):
        import httpx
        raise httpx.ConnectError("refused")

    async def __aexit__(self, *args):
        pass


def _mock_ollama_stream(text: str):
    """Return an AsyncMock httpx client that streams *text* via client.stream (reply tests)."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = MagicMock(return_value=_FakeStreamResp(text))
    # Keep post/get for resolver/config tests that might also be patched
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.get = AsyncMock(return_value=mock_resp)
    return mock_client


def _mock_ollama_down():
    """Return an AsyncMock client that raises a connection error on post, get, and stream."""
    import httpx
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_client.stream = MagicMock(return_value=_FailStreamCtx())
    return mock_client


# ---------------------------------------------------------------------------
# _build_extraction_prompt
# ---------------------------------------------------------------------------

def test_prompt_includes_utterance():
    prompt = _build_extraction_prompt("can I buy it?", ["navy blazer"], "navy blazer")
    assert "can I buy it?" in prompt

def test_prompt_includes_wardrobe():
    prompt = _build_extraction_prompt("buy it", ["navy blazer", "white shirt"], None)
    assert "navy blazer" in prompt
    assert "white shirt" in prompt

def test_prompt_includes_last_mentioned():
    prompt = _build_extraction_prompt("buy it", [], "leather jacket")
    assert "leather jacket" in prompt

def test_prompt_handles_empty_wardrobe():
    prompt = _build_extraction_prompt("buy it", [], None)
    assert "empty" in prompt


# ---------------------------------------------------------------------------
# llm_resolve — happy path
# ---------------------------------------------------------------------------

async def test_llm_resolve_returns_llm_item():
    state = new_session()
    add_wardrobe_item(state, "navy blazer")

    with patch("httpx.AsyncClient", return_value=_mock_ollama_response("navy blazer")):
        item, source = await llm_resolve("can I buy it?", state)

    assert item == "navy blazer"
    assert source == "llm"


async def test_llm_resolve_strips_and_lowercases():
    state = new_session()
    with patch("httpx.AsyncClient", return_value=_mock_ollama_response("  Navy Blazer  ")):
        item, source = await llm_resolve("buy the blazer", state)

    assert item == "navy blazer"
    assert source == "llm"


# ---------------------------------------------------------------------------
# llm_resolve — fallback paths
# ---------------------------------------------------------------------------

async def test_llm_resolve_falls_back_on_connection_error():
    """Ollama down → silently falls back to heuristic."""
    state = new_session()
    add_wardrobe_item(state, "navy blazer")

    with patch("httpx.AsyncClient", return_value=_mock_ollama_down()):
        item, source = await llm_resolve("can I buy my navy blazer?", state)

    # Heuristic finds "navy blazer" via exact wardrobe match.
    assert item == "navy blazer"
    assert source == "explicit"


async def test_llm_resolve_falls_back_on_none_response():
    """LLM replies 'none' → fall back to heuristic."""
    state = new_session()
    set_last_mentioned_item(state, "leather jacket")

    with patch("httpx.AsyncClient", return_value=_mock_ollama_response("none")):
        item, source = await llm_resolve("I need help", state)

    # Heuristic falls back to last_mentioned_item.
    assert item == "leather jacket"
    assert source == "heuristic:last_mentioned"


async def test_llm_resolve_falls_back_on_empty_response():
    state = new_session()
    with patch("httpx.AsyncClient", return_value=_mock_ollama_response("")):
        item, source = await llm_resolve("help me", state)
    # No wardrobe, no last_mentioned → none
    assert item is None
    assert source == "none"


async def test_llm_resolve_falls_back_on_http_error():
    import httpx
    state = new_session()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock()
    ))

    with patch("httpx.AsyncClient", return_value=mock_client):
        item, source = await llm_resolve("buy it", state)

    # Falls back to heuristic with no wardrobe or last_mentioned.
    assert source in ("none", "explicit", "heuristic:last_mentioned")


# ---------------------------------------------------------------------------
# config.bootstrap — LLM_ENABLED env var
# ---------------------------------------------------------------------------

async def test_bootstrap_llm_disabled_returns_heuristic(monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "false")
    from mrshop import config
    with patch("mrshop.classifier.tier2.load_model"):  # skip model load
        resolver, reply_fn = await config.bootstrap()
    assert resolver is heuristic_resolve


async def test_bootstrap_llm_enabled_returns_llm(monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "true")
    from mrshop import config
    with patch("mrshop.classifier.tier2.load_model"):
        resolver, reply_fn = await config.bootstrap()
    assert resolver is llm_resolve


async def test_bootstrap_auto_ollama_up_returns_llm(monkeypatch):
    monkeypatch.delenv("LLM_ENABLED", raising=False)
    from mrshop import config

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("mrshop.classifier.tier2.load_model"), \
         patch("httpx.AsyncClient", return_value=mock_client):
        resolver, reply_fn = await config.bootstrap()

    assert resolver is llm_resolve


async def test_bootstrap_auto_ollama_down_returns_heuristic(monkeypatch):
    monkeypatch.delenv("LLM_ENABLED", raising=False)
    from mrshop import config

    with patch("mrshop.classifier.tier2.load_model"), \
         patch("httpx.AsyncClient", return_value=_mock_ollama_down()):
        resolver, reply_fn = await config.bootstrap()

    assert resolver is heuristic_resolve


# ---------------------------------------------------------------------------
# End-to-end: orchestrator with llm_resolve injected
# ---------------------------------------------------------------------------

async def test_orchestrator_uses_llm_resolver_source_label():
    """
    Wire llm_resolve into the orchestrator and verify the reply uses the
    LLM-resolved item.  HTTP call is mocked to return "navy blazer".
    """
    state = new_session()
    add_wardrobe_item(state, "navy blazer")
    set_last_mentioned_item(state, "navy blazer")

    orch = Orchestrator(resolve_reference=llm_resolve, generate_reply=template_reply, state=state)

    with patch("httpx.AsyncClient", return_value=_mock_ollama_response("navy blazer")):
        reply, trace = await orch.handle_turn("I want to buy that jacket")

    assert "purchase" in trace["tools_invoked"]
    assert "navy blazer" in reply or "jacket" in reply


async def test_orchestrator_falls_back_gracefully_when_ollama_down():
    """
    Even with llm_resolve injected, the system stays functional when
    Ollama is unreachable — reply is generated, no exception raised.
    """
    state = new_session()
    set_last_mentioned_item(state, "navy blazer")
    orch = Orchestrator(resolve_reference=llm_resolve, generate_reply=template_reply, state=state)

    with patch("httpx.AsyncClient", return_value=_mock_ollama_down()):
        reply, trace = await orch.handle_turn("I want to buy it")

    # Heuristic fallback served the request.
    assert "purchase" in trace["tools_invoked"]
    assert reply  # non-empty reply


# ---------------------------------------------------------------------------
# llm_reply — happy path and fallbacks
# ---------------------------------------------------------------------------

class TestLlmReply:
    async def test_llm_reply_returns_ollama_text(self):
        """Ollama responds via streaming → reply uses the LLM-generated text."""
        state = new_session()
        result = {"status": "added", "item": "navy blazer", "wardrobe_size": 1}

        with patch("httpx.AsyncClient", return_value=_mock_ollama_stream(
            "Great choice! I've added your navy blazer to your wardrobe."
        )):
            reply = await llm_reply("I just got a navy blazer", "wardrobe_upload",
                                    result, "navy blazer", "explicit", state)

        assert "navy blazer" in reply

    async def test_llm_reply_calls_on_token_during_stream(self):
        """on_token callback is invoked with each streamed chunk."""
        state = new_session()
        result = {"status": "added", "item": "navy blazer", "wardrobe_size": 1}
        received: list[str] = []

        with patch("httpx.AsyncClient", return_value=_mock_ollama_stream("navy blazer added!")):
            reply = await llm_reply(
                "I just got a navy blazer", "wardrobe_upload",
                result, "navy blazer", "explicit", state,
                on_token=received.append,
            )

        assert received  # at least one chunk received
        assert "navy blazer added!" in "".join(received)

    async def test_llm_reply_falls_back_on_connection_error(self):
        """Ollama down → template_reply takes over; result is non-empty."""
        state = new_session()
        result = {"status": "added", "item": "navy blazer", "wardrobe_size": 1}

        with patch("httpx.AsyncClient", return_value=_mock_ollama_down()):
            reply = await llm_reply("I just got a navy blazer", "wardrobe_upload",
                                    result, "navy blazer", "explicit", state)

        # Falls back to template — should still mention the item.
        assert reply
        assert "navy blazer" in reply

    async def test_llm_reply_falls_back_on_empty_response(self):
        """LLM streams empty string → template fallback."""
        state = new_session()
        result = {"status": "added", "item": "leather jacket", "wardrobe_size": 1}

        with patch("httpx.AsyncClient", return_value=_mock_ollama_stream("")):
            reply = await llm_reply("I got a leather jacket", "wardrobe_upload",
                                    result, "leather jacket", "explicit", state)

        assert reply
        assert "leather jacket" in reply

    async def test_llm_reply_unclear_intent_mentions_capabilities(self):
        """For 'unclear' intent, LLM reply covers at least one capability."""
        state = new_session()

        with patch("httpx.AsyncClient", return_value=_mock_ollama_stream(
            "Hi! I can help you with wardrobe management, styling advice, purchases, or booking a stylist."
        )):
            reply = await llm_reply("Hello", "unclear", {}, None, "none", state)

        capability_words = {"wardrobe", "styling", "purchase", "booking", "stylist", "help"}
        assert any(w in reply.lower() for w in capability_words)

    async def test_orchestrator_with_llm_reply_end_to_end(self):
        """Full turn with llm_reply: orchestrator calls LLM for response."""
        state = new_session()
        orch = Orchestrator(
            resolve_reference=heuristic_resolve,
            generate_reply=llm_reply,
            state=state,
        )

        with patch("httpx.AsyncClient", return_value=_mock_ollama_stream(
            "Done! Your navy blazer is now in your wardrobe."
        )):
            reply, trace = await orch.handle_turn("I just got a navy blazer")

        assert "wardrobe_upload" in trace["tools_invoked"]
        assert reply
        assert "navy blazer" in reply or "wardrobe" in reply
