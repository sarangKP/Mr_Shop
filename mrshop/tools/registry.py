"""
Tool registry — the single place that defines everything about an intent.

Adding a new capability means creating one file, calling register(), and nothing else.
The classifiers, orchestrator, and reply generator all read from this registry at
runtime — no other files need to change.

ToolDefinition fields:
  intent               — unique string label (e.g. "size_check")
  tier1_patterns       — regex strings; matched top-priority-first across all tools
  tier2_examples       — representative sentences for embedding similarity matching
  llm_instruction      — injected into the LLM reply prompt for this intent
  run                  — the tool function: (utterance, resolved_item, state) -> dict
  tier1_priority       — lower = evaluated earlier in Tier 1 (default 99)
  use_heuristic_resolver — bypass LLM resolver; use regex extraction instead
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class ToolDefinition:
    intent: str
    tier1_patterns: list[str]
    tier2_examples: list[str]
    llm_instruction: str
    run: Callable  # (utterance: str, resolved_item: Optional[str], state: dict) -> dict
    tier1_priority: int = 99
    use_heuristic_resolver: bool = False


_registry: dict[str, ToolDefinition] = {}
_discovered = False


def register(tool: ToolDefinition) -> None:
    """Register a tool definition. Called once per tool at module import time."""
    _registry[tool.intent] = tool


def get(intent: str) -> Optional[ToolDefinition]:
    """Look up a registered tool by intent label. Returns None for 'unclear'."""
    return _registry.get(intent)


def _ensure_tools_loaded() -> None:
    """Auto-import all tool modules in mrshop/tools/ so they can self-register.

    Uses pkgutil to discover modules dynamically — adding a new tool file is
    sufficient; no manual list to maintain here.
    """
    global _discovered
    if _discovered:
        return
    _discovered = True
    import importlib
    import pkgutil
    import mrshop.tools as _pkg
    for _finder, _name, _ispkg in pkgutil.iter_modules(_pkg.__path__, "mrshop.tools."):
        if _name not in ("mrshop.tools.registry",):
            importlib.import_module(_name)


def all_tools() -> list[ToolDefinition]:
    """Return all registered tools sorted by tier1_priority."""
    _ensure_tools_loaded()
    return sorted(_registry.values(), key=lambda t: t.tier1_priority)


def get_intents() -> tuple[str, ...]:
    """Return all registered intent labels plus the built-in 'unclear' catch-all."""
    _ensure_tools_loaded()
    return tuple(t.intent for t in sorted(_registry.values(), key=lambda t: t.tier1_priority)) + ("unclear",)
