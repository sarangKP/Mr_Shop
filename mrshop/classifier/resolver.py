"""
Reference resolver — the clean, swappable interface for slot extraction.

The orchestrator always calls `await resolve_reference(utterance, memory)`
and never checks LLM_ENABLED itself.  At startup, config.bootstrap()
selects one of the two concrete implementations below and injects it
into the Orchestrator constructor.

Both implementations share the same async signature so the orchestrator
is completely unaware of which one is active:
  - heuristic_resolve  →  sync logic wrapped as a trivial coroutine
  - llm_resolve        →  async HTTP call to Ollama; falls back to heuristic
                           on any failure so degraded mode is always available

Return type:  (resolved_item | None, source_label)
  source_label: "explicit" | "heuristic:last_mentioned" | "llm" | "none"
"""

from __future__ import annotations

import os
import re
from typing import Callable, Coroutine, Optional

# Type alias — async callable used by the orchestrator.
ResolverFn = Callable[[str, dict], Coroutine[None, None, tuple[Optional[str], str]]]

# ---------------------------------------------------------------------------
# Clothing vocabulary — used by the heuristic extractor.
# ---------------------------------------------------------------------------

_CLOTHING_WORDS = {
    "blazer", "jacket", "shirt", "jeans", "pants", "shoes", "boots",
    "coat", "sweater", "dress", "suit", "tie", "scarf", "hat", "bag",
    "sneakers", "loafers", "trousers", "chinos", "hoodie", "cardigan",
    "top", "skirt", "shorts", "vest", "tuxedo", "overcoat", "parka",
}

_SKIP_ADJECTIVES = {
    "a", "an", "the", "my", "your", "their", "our", "its",
    "this", "that", "these", "those", "some", "any", "no",
    "new", "old", "nice", "good", "great", "cool",
    "i", "we", "he", "she", "they",
}

_ITEM_PATTERN = re.compile(
    r"\b(?:(\w+)\s+)?(" + "|".join(re.escape(w) for w in _CLOTHING_WORDS) + r")\b",
    re.IGNORECASE,
)

_BULK_REF_RE = re.compile(
    r"\b(those|them|these|all of them|the ones|those items|these items|they)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Heuristic implementation — always available, no LLM required
# ---------------------------------------------------------------------------

async def heuristic_resolve(utterance: str, memory: dict) -> tuple[Optional[str], str]:
    """
    Resolve item references without an LLM.

    Strategy (in order):
      1. Exact wardrobe item match in utterance.
      2. Regex extraction of [adjective +] clothing noun.
      3. Fall back to memory["last_mentioned_item"] and say so explicitly.
      4. Return (None, "none") if nothing found.
    """
    lower = utterance.lower()

    # 1. Exact wardrobe item match
    for item in memory.get("wardrobe_items", []):
        if item.lower() in lower:
            return item, "explicit"

    # 2. Regex: extract adjective + clothing noun
    match = _ITEM_PATTERN.search(utterance)
    if match:
        adjective, noun = match.group(1), match.group(2)
        if adjective and adjective.lower() in _SKIP_ADJECTIVES:
            adjective = None
        item = f"{adjective} {noun}".strip().lower() if adjective else noun.lower()
        return item, "explicit"

    # 2.5. Bulk-reference pronoun ("those", "them", "these") → prefer last suggested items
    if _BULK_REF_RE.search(utterance):
        suggested = memory.get("last_suggested_items", [])
        if suggested:
            return suggested[0], "heuristic:suggested"

    # 3. Fall back to last_mentioned_item
    last = memory.get("last_mentioned_item")
    if last:
        return last, "heuristic:last_mentioned"

    return None, "none"


# ---------------------------------------------------------------------------
# LLM implementation — Ollama (Step 9)
# ---------------------------------------------------------------------------

def _build_extraction_prompt(
    utterance: str,
    wardrobe: list[str],
    last_item: Optional[str],
    suggested_items: Optional[list[str]] = None,
) -> str:
    """Build a compact prompt for Ollama to extract the referenced item."""
    wardrobe_str = ", ".join(wardrobe) if wardrobe else "empty"
    last_str = last_item or "none"
    suggested_str = ", ".join(suggested_items) if suggested_items else "none"
    return (
        "You are a fashion assistant helping identify clothing item references.\n\n"
        f"User's wardrobe: {wardrobe_str}\n"
        f"Last mentioned item: {last_str}\n"
        f"Recently suggested items: {suggested_str}\n"
        f'User said: "{utterance}"\n\n'
        "Reply with ONLY the clothing item name the user is referring to "
        '(e.g. "navy blazer", "leather jacket"). '
        'If they use a pronoun like "it" or "that", resolve it from context. '
        'If they say "those items" or "them" and there are recently suggested items, '
        'return the most relevant suggested item. '
        'If no item can be determined, reply with "none". '
        "Do not explain or add any other text."
    )


async def llm_resolve(utterance: str, memory: dict) -> tuple[Optional[str], str]:
    """
    Resolve item references via the local Ollama LLM.

    Reads OLLAMA_HOST (default: http://localhost:11434) and OLLAMA_MODEL
    (default: llama3.2:3b) from the environment.

    Falls back silently to heuristic_resolve if:
      - Ollama is unreachable
      - The HTTP request fails
      - The response is empty or "none"

    This guarantees degraded mode always works even when LLM_ENABLED=true
    but Ollama becomes unavailable mid-session.
    """
    import httpx  # imported here so the module loads without httpx in test-only envs

    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

    wardrobe = memory.get("wardrobe_items", [])
    last = memory.get("last_mentioned_item")
    suggested = memory.get("last_suggested_items", [])
    prompt = _build_extraction_prompt(utterance, wardrobe, last, suggested or None)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{host}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "").strip().lower()
    except Exception:
        # Any failure — network error, timeout, bad JSON — falls through.
        return await heuristic_resolve(utterance, memory)

    if not raw or raw == "none":
        return await heuristic_resolve(utterance, memory)

    return raw, "llm"
