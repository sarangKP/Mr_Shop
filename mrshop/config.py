"""
Startup configuration — the single place that reads LLM_ENABLED and wires
the correct resolver and reply-generator implementations into the orchestrator.

Nothing else reads LLM_ENABLED.  Everything else calls bootstrap() and
receives both functions via DI; it is unaware of which implementations are active.

Environment variables:
  LLM_ENABLED   "true" | "false" | unset (autodetect by pinging Ollama)
  OLLAMA_HOST   default: http://localhost:11434
  OLLAMA_MODEL  default: llama3.2:3b
"""

from __future__ import annotations

import os

# Import tool modules to trigger self-registration in the tool registry.
# Must run before any classifier or orchestrator reads from the registry.
import mrshop.tools.wardrobe  # noqa: F401
import mrshop.tools.styling   # noqa: F401
import mrshop.tools.purchase  # noqa: F401
import mrshop.tools.booking   # noqa: F401

from mrshop.classifier.resolver import ResolverFn, heuristic_resolve, llm_resolve
from mrshop.classifier.tier2 import load_model as load_embedding_model
from mrshop.generator.reply import ReplyFn, template_reply, llm_reply

_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


async def _ollama_reachable() -> bool:
    """Ping Ollama's tag-list endpoint; return True if it responds 200."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{_OLLAMA_HOST}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


async def bootstrap() -> tuple[ResolverFn, ReplyFn]:
    """
    Perform all one-time startup work and return (resolver, reply_generator).

    Called once from the REPL before the first turn via asyncio.run().

    Decision logic:
      LLM_ENABLED=true   → (llm_resolve,       llm_reply)
      LLM_ENABLED=false  → (heuristic_resolve,  template_reply)
      unset / "auto"     → ping Ollama; LLM pair if up, heuristic pair if not
    """
    load_embedding_model()

    setting = os.getenv("LLM_ENABLED", "auto").strip().lower()
    model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

    if setting == "false":
        print("[config] LLM_ENABLED=false — resolver=heuristic, reply=template")
        return heuristic_resolve, template_reply

    if setting == "true":
        print(f"[config] LLM_ENABLED=true — resolver=llm, reply=llm ({_OLLAMA_HOST}, model={model})")
        return llm_resolve, llm_reply

    # Auto-detect: ping Ollama.
    if await _ollama_reachable():
        print(f"[config] Ollama detected at {_OLLAMA_HOST} — resolver=llm, reply=llm (model={model})")
        return llm_resolve, llm_reply

    print(f"[config] Ollama not found at {_OLLAMA_HOST} — resolver=heuristic, reply=template")
    return heuristic_resolve, template_reply


def get_resolver_and_reply() -> tuple[ResolverFn, ReplyFn]:
    """
    Return (heuristic_resolve, template_reply) — for tests that don't need
    the full bootstrap (no embedding model load, no Ollama ping).
    """
    return heuristic_resolve, template_reply
