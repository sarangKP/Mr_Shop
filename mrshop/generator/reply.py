"""
Reply generation — the swappable response layer.

Mirrors the resolver DI pattern: two async implementations behind one type alias.
  - template_reply  →  deterministic template strings (current _build_reply logic)
  - llm_reply       →  Ollama prompt with full session context; falls back to
                        template_reply on any failure

Both share the same signature so the orchestrator never checks LLM_ENABLED.
bootstrap() in config.py selects which one to inject.

Return value: plain reply string ready to print to the user.
"""

from __future__ import annotations

import json
import os
from typing import Callable, Coroutine, Optional

from mrshop.memory import session

# Async callable injected into Orchestrator.
ReplyFn = Callable[
    [str, str, dict, Optional[str], str, dict],
    Coroutine[None, None, str],
]
# args: utterance, intent, result, resolved_item, resolve_source, state


# ---------------------------------------------------------------------------
# Intent-specific LLM instructions — read from tool registry + "unclear" fallback
# ---------------------------------------------------------------------------

_instructions_cache: dict[str, str] | None = None

_UNCLEAR_INSTRUCTION = (
    "Greet the user warmly. Briefly explain what you can help with: wardrobe "
    "management, styling advice, purchases, and booking a stylist. Ask what "
    "they'd like to do. 2–3 sentences, conversational."
)

_DEFAULT_INSTRUCTION = (
    "Generate a natural, friendly response acknowledging the user's request. "
    "Keep it 2–4 sentences."
)


def _get_instructions() -> dict[str, str]:
    global _instructions_cache
    if _instructions_cache is not None:
        return _instructions_cache
    from mrshop.tools.registry import all_tools
    instructions = {t.intent: t.llm_instruction for t in all_tools()}
    instructions["unclear"] = _UNCLEAR_INSTRUCTION
    _instructions_cache = instructions
    return _instructions_cache


# ---------------------------------------------------------------------------
# Template implementation — deterministic, no LLM
# ---------------------------------------------------------------------------

async def template_reply(
    utterance: str,
    intent: str,
    result: dict,
    resolved_item: Optional[str],
    resolve_source: str,
    state: dict,
    *,
    on_token=None,
) -> str:
    """Deterministic template-based reply. Used in tests and as LLM fallback."""
    assumption = ""
    if resolve_source == "heuristic:last_mentioned" and resolved_item:
        assumption = (
            f"\n(I'm assuming you mean '{resolved_item}' — "
            "let me know if you meant something else.)"
        )

    if intent == "wardrobe_upload":
        item = result["item"]
        if result["status"] == "added":
            reply = (
                f"Got it! I've added '{item}' to your wardrobe. "
                f"You now have {result['wardrobe_size']} item(s)."
                + assumption
            )
        else:
            reply = (
                f"You already have '{item}' in your wardrobe "
                f"({result['wardrobe_size']} item(s) total)."
                + assumption
            )

    elif intent == "wardrobe_list":
        items = result.get("items", [])
        if not items:
            reply = "Your wardrobe is empty. Tell me what you own and I'll add it!"
        else:
            lines = [f"Here's what you have in your wardrobe ({result['count']} item(s)):"]
            for i, item in enumerate(items, 1):
                lines.append(f"  {i}. {item}")
            reply = "\n".join(lines)

    elif intent == "styling_advice":
        lines = ["Here are some outfit ideas:"]
        for i, suggestion in enumerate(result["suggestions"][:3], 1):
            lines.append(f"  {i}. {suggestion}")
        if result["based_on_wardrobe"]:
            lines.append(f"(Based on your wardrobe: {', '.join(result['based_on_wardrobe'])})")
        reply = "\n".join(lines) + assumption

    elif intent == "purchase":
        status = result.get("status")
        if status == "already_owned":
            reply = (
                f"'{result['item']}' is already in your wardrobe — you own it! "
                "No need to buy it again." + assumption
            )
        elif status == "bulk_purchase":
            items = result.get("items_purchased", [])
            cart_size = len(result.get("cart", []))
            if items:
                names = ", ".join(f"'{i}'" for i in items)
                reply = (
                    f"Added {names} to your cart. "
                    f"Your cart now has {cart_size} item(s)."
                    + assumption
                )
            else:
                reply = "All suggested items are already in your wardrobe — nothing new to buy!"
        elif not result:
            reply = "I'm not sure what you'd like to buy. Could you be more specific?" + assumption
        else:
            item = result["item"]
            price = result["price_usd"]
            cart_size = len(result["cart"])
            reply = (
                f"Purchase started for '{item}' at ${price:.2f}. "
                f"Your cart now has {cart_size} item(s)."
                + assumption
            )

    elif intent == "booking":
        reply = (
            f"Booked! Stylist {result['stylist']} will see you: {result['slot']}. "
            f"Confirmation: {result['confirmation']}."
            + assumption
        )

    else:
        reply = (
            "I'm not sure how to help with that. Could you tell me more? "
            "I can help with: adding wardrobe items, styling advice, "
            "purchases, or booking a stylist."
        )

    if on_token:
        on_token(reply)
    return reply


# ---------------------------------------------------------------------------
# LLM implementation — Ollama
# ---------------------------------------------------------------------------

def _build_reply_prompt(
    utterance: str,
    intent: str,
    result: dict,
    resolved_item: Optional[str],
    resolve_source: str,
    state: dict,
) -> str:
    """Build the Ollama prompt for reply generation."""
    wardrobe = session.get(state, "wardrobe_items")
    prefs = session.get(state, "preferences")
    gender = session.get(state, "gender")
    budget = session.get(state, "budget")
    history = session.get(state, "topic_history")
    last_item = session.get(state, "last_mentioned_item")

    context_lines = []
    context_lines.append(f"Wardrobe: {', '.join(wardrobe) if wardrobe else 'empty'}")
    if gender:
        context_lines.append(f"Gender: {gender}")
    if budget is not None:
        context_lines.append(f"Budget: ${budget:.2f}")
    if prefs.get("style"):
        context_lines.append(f"Style preference: {prefs['style']}")
    if prefs.get("colors"):
        context_lines.append(f"Favourite colours: {', '.join(prefs['colors'])}")
    if history:
        context_lines.append(f"Previous topic: {history[-1]}")
    if last_item:
        context_lines.append(f"Last mentioned item: {last_item}")

    context_str = "\n".join(context_lines)
    tool_result_str = json.dumps(result, indent=2) if result else "{}"
    instruction = _get_instructions().get(intent, _DEFAULT_INSTRUCTION)

    return (
        "You are Mr.Shop, a personal styling assistant built into a terminal.\n"
        "Respond naturally in 2–4 sentences. Never mention tools, intents, or internal details.\n\n"
        "[SESSION CONTEXT]\n"
        f"{context_str}\n\n"
        "[CURRENT TURN]\n"
        f'User said: "{utterance}"\n'
        f"Intent: {intent} | Resolved item: {resolved_item or 'none'} (source: {resolve_source})\n\n"
        "[TOOL RESULT]\n"
        f"{tool_result_str}\n\n"
        "[INSTRUCTION]\n"
        f"{instruction}\n\n"
        "Reply with ONLY the response text. No markdown, no quotation marks."
    )


async def llm_reply(
    utterance: str,
    intent: str,
    result: dict,
    resolved_item: Optional[str],
    resolve_source: str,
    state: dict,
    *,
    on_token=None,
) -> str:
    """
    Generate a conversational reply via the local Ollama LLM (streaming).

    Reads OLLAMA_HOST (default: http://localhost:11434) and OLLAMA_MODEL
    (default: llama3.2:3b) from the environment.

    When on_token is provided, each token is passed to it as it arrives so
    the caller can stream output to the terminal in real time.

    Falls back silently to template_reply on any failure so degraded mode
    always works even when Ollama becomes unavailable mid-session.
    """
    import httpx

    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    prompt = _build_reply_prompt(utterance, intent, result, resolved_item, resolve_source, state)

    accumulated: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream(
                "POST",
                f"{host}/api/generate",
                json={"model": model, "prompt": prompt, "stream": True},
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    chunk = data.get("response", "")
                    if chunk:
                        accumulated.append(chunk)
                        if on_token:
                            on_token(chunk)
                    if data.get("done"):
                        break
    except Exception:
        return await template_reply(
            utterance, intent, result, resolved_item, resolve_source, state, on_token=on_token
        )

    full_reply = "".join(accumulated)
    if not full_reply:
        return await template_reply(
            utterance, intent, result, resolved_item, resolve_source, state, on_token=on_token
        )
    return full_reply
