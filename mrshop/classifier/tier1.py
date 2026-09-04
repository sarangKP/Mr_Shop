"""
Tier 1 intent classifier — keyword / regex rules (PRD §7).

Rules are loaded lazily from the tool registry on first classify() call.
To add a new intent, register a ToolDefinition in its tool file — no changes
needed here.
"""

import re
from typing import Optional

_rules_cache: list[tuple[re.Pattern, str]] | None = None


def _get_rules() -> list[tuple[re.Pattern, str]]:
    global _rules_cache
    if _rules_cache is not None:
        return _rules_cache
    from mrshop.tools.registry import all_tools
    compiled = [
        (re.compile(pattern, re.IGNORECASE), tool.intent)
        for tool in all_tools()
        for pattern in tool.tier1_patterns
    ]
    _rules_cache = compiled
    return _rules_cache


def classify(utterance: str) -> tuple[Optional[str], float]:
    """
    Apply keyword/regex rules to *utterance*.

    Returns:
        (intent, 1.0)  — definite rule hit
        (None,  0.0)   — no rule matched; Tier 2 should take over
    """
    for pattern, intent in _get_rules():
        if pattern.search(utterance):
            return intent, 1.0
    return None, 0.0


def get_intents() -> tuple[str, ...]:
    """Return all registered intent labels plus the 'unclear' catch-all."""
    from mrshop.tools.registry import get_intents as _reg_intents
    return _reg_intents()


def _reset_cache() -> None:
    """Clear the compiled rule cache. Useful in tests that modify the registry."""
    global _rules_cache
    _rules_cache = None
