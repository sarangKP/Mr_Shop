"""
Orchestrator — the agent brain (PRD §6, §9).

Coordinates memory, classifiers, resolver, and tools for one user turn.
Produces a (reply, turn_trace) pair per turn.

The orchestrator:
  - Never checks LLM_ENABLED — it receives ResolverFn and ReplyFn at construction time.
  - Runs Tier 1 → Tier 2 classification in order; falls to generate_reply for low
    confidence (including greetings like "Hello") instead of a canned clarification.
  - Calls resolve_reference for every turn so item references are handled consistently.
  - Updates session memory after every turn.
  - Records a turn_trace (PRD §9) for observability.
"""

from __future__ import annotations

import time
from typing import Optional

import re

from mrshop.classifier import tier1, tier2
from mrshop.classifier.resolver import ResolverFn, heuristic_resolve
from mrshop.generator.reply import ReplyFn
from mrshop.memory import session
from mrshop.tools.registry import get as get_tool_def


class Orchestrator:
    """Agent brain: processes one user turn and returns (reply, turn_trace)."""

    def __init__(
        self,
        resolve_reference: ResolverFn,
        generate_reply: ReplyFn,
        state: dict,
    ) -> None:
        self._resolve_reference = resolve_reference
        self._generate_reply = generate_reply
        self._state = state
        self._turn_id = 0

    async def handle_turn(self, utterance: str, on_token=None) -> tuple[str, dict]:
        """
        Process one user utterance end-to-end.

        Pipeline:
          RECEIVED → CLASSIFYING → ROUTING → TOOL_CALL → MEMORY_UPDATE
          → RESPONDING → DONE
        """
        self._turn_id += 1
        t_start = time.time()

        trace = _new_trace(self._turn_id)
        trace["stage"] = "CLASSIFYING"

        # ------------------------------------------------------------------
        # Tier 1 — keyword / regex rules (instant)
        # ------------------------------------------------------------------
        t1_start = time.time()
        intent, confidence = tier1.classify(utterance)
        trace["latency_ms"]["tier1_ms"] = _ms(t1_start)

        if intent is not None:
            trace["intent_source"] = "rule"
            trace["confidence"] = confidence
        else:
            # ---------------------------------------------------------------
            # Tier 2 — embedding similarity (CPU, <100ms)
            # ---------------------------------------------------------------
            t2_start = time.time()
            intent, confidence = tier2.classify(utterance)
            trace["latency_ms"]["tier2_ms"] = _ms(t2_start)

            if intent is not None:
                trace["intent_source"] = "embedding"
                trace["confidence"] = round(confidence, 3)
            else:
                # Low confidence — treat as "unclear"; LLM will handle naturally.
                intent = "unclear"
                trace["intent_source"] = "clarify"
                trace["confidence"] = round(confidence, 3)

        # ------------------------------------------------------------------
        # ROUTING — topic switch detection + reference resolution
        # ------------------------------------------------------------------
        trace["stage"] = "ROUTING"

        current_topic = session.get(self._state, "current_topic")
        if current_topic is not None and current_topic != intent and intent != "unclear":
            trace["topic_switch"] = True

        session.switch_topic(self._state, intent)

        # Resolution strategy depends on intent:
        #  - "unclear": no tool, no item needed — skip entirely to avoid LLM
        #    extracting garbage words (e.g. "hello") as item references.
        #  - use_heuristic_resolver tools: extract a *new* item via regex only
        #    (LLM would wrongly map new declarations to existing wardrobe items).
        #  - everything else: use the injected resolver (heuristic or LLM).
        _tool_def = get_tool_def(intent)
        if intent == "unclear":
            resolved_item, resolve_source = None, "none"
        elif _tool_def is not None and _tool_def.use_heuristic_resolver:
            resolved_item, resolve_source = await heuristic_resolve(utterance, self._state)
        else:
            resolved_item, resolve_source = await self._resolve_reference(utterance, self._state)
        trace["resolver_source"] = resolve_source

        # ------------------------------------------------------------------
        # TOOL_CALL
        # ------------------------------------------------------------------
        trace["stage"] = "TOOL_CALL"
        tool_start = time.time()
        result = _dispatch_tool(intent, utterance, resolved_item, self._state)
        trace["latency_ms"]["tool_ms"] = _ms(tool_start)
        if intent not in ("unclear",):
            trace["tools_invoked"].append(intent)

        # ------------------------------------------------------------------
        # MEMORY_UPDATE
        # ------------------------------------------------------------------
        trace["stage"] = "MEMORY_UPDATE"
        if resolved_item and session.get(self._state, "last_mentioned_item") != resolved_item:
            session.set_last_mentioned_item(self._state, resolved_item)

        # Opportunistically extract gender, budget, and preferences from any utterance.
        gender = _extract_gender(utterance)
        if gender:
            session.set_gender(self._state, gender)

        budget = _extract_budget(utterance)
        if budget is not None:
            session.set_budget(self._state, budget)

        style, colors = _extract_preferences(utterance)
        if style or colors:
            session.update_preferences(
                self._state,
                style=style if style else None,
                colors=colors if colors else None,
            )

        # ------------------------------------------------------------------
        # RESPONDING
        # ------------------------------------------------------------------
        trace["stage"] = "RESPONDING"
        reply = await self._generate_reply(
            utterance, intent, result, resolved_item, resolve_source, self._state,
            on_token=on_token,
        )

        trace["stage"] = "DONE"
        trace["latency_ms"]["total_ms"] = _ms(t_start)
        return reply, trace


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _new_trace(turn_id: int) -> dict:
    """Return a fresh turn_trace matching the PRD §9 schema."""
    return {
        "turn_id": turn_id,
        "stage": "RECEIVED",
        "intent_source": None,
        "confidence": None,
        "resolver_source": None,
        "tools_invoked": [],
        "topic_switch": False,
        "latency_ms": {},
    }


def _ms(t_start: float) -> float:
    """Milliseconds elapsed since t_start, rounded to 1 dp."""
    return round((time.time() - t_start) * 1000, 1)


def _dispatch_tool(
    intent: str,
    utterance: str,
    resolved_item: Optional[str],
    state: dict,
) -> dict:
    """Route to the registered tool function and return its result dict."""
    tool = get_tool_def(intent)
    if tool is None:
        # "unclear" has no registered tool; generate_reply handles it.
        return {}
    return tool.run(utterance, resolved_item, state)


# ---------------------------------------------------------------------------
# Gender extraction — runs on every utterance as a side-channel update
# ---------------------------------------------------------------------------

_GENDER_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(i'?m|i am|as a)\s+(a\s+)?(woman|female|girl|lady)\b", re.IGNORECASE), "female"),
    (re.compile(r"\b(i'?m|i am|as a)\s+(a\s+)?(man|male|guy|dude|bloke)\b", re.IGNORECASE), "male"),
    (re.compile(r"\bmy gender is\s+(female|woman|girl)\b", re.IGNORECASE), "female"),
    (re.compile(r"\bmy gender is\s+(male|man|boy)\b", re.IGNORECASE), "male"),
    (re.compile(r"\bshe/her\b", re.IGNORECASE), "female"),
    (re.compile(r"\bhe/him\b", re.IGNORECASE), "male"),
]


def _extract_gender(utterance: str) -> Optional[str]:
    """Return a gender label if the utterance contains a clear self-identification, else None."""
    for pattern, label in _GENDER_RULES:
        if pattern.search(utterance):
            return label
    return None


# ---------------------------------------------------------------------------
# Budget extraction — runs on every utterance as a side-channel update
# ---------------------------------------------------------------------------

_BUDGET_RE = re.compile(
    r"(?:"
    r"\$\s*(\d{1,6}(?:[.,]\d{1,2})?)"        # $200 / $ 200 / $1,500
    r"|(\d{1,6}(?:[.,]\d{1,2})?)\s*\$"        # 200$ / 1500 $
    r"|budget\b.{0,20}?(\d{1,6}(?:[.,]\d{1,2})?)"  # budget is 200 / budget of 150
    r")",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Preference extraction — style and colour signals, side-channel update
# ---------------------------------------------------------------------------

_STYLE_RE = re.compile(
    r"\b(?:style(?:\s+is)?|i\s+(?:like|love|prefer|am\s+into)|going\s+for|i(?:'m|\s+am)\s+into)\b"
    r".{0,30}\b(minimalist|casual|smart\s+casual|formal|streetwear|classic|bohemian|"
    r"athletic|preppy|vintage|elegant|sporty|edgy|urban)\b",
    re.IGNORECASE,
)

# Color words present in a sentence that expresses a preference.
_COLOR_CONTEXT_RE = re.compile(
    r"\b(?:i\s+(?:like|love|prefer|wear|gravitate|tend\s+to\s+wear)|"
    r"(?:my\s+)?favou?rite|i(?:'m|\s+am)\s+(?:a\s+fan|into)|go\s+for)\b",
    re.IGNORECASE,
)

_COLOR_FIND_RE = re.compile(
    r"\b(navy|black|white|grey|gray|beige|brown|red|blue|green|yellow|pink|"
    r"purple|orange|khaki|olive|burgundy|cream|tan|teal|mustard|charcoal|neutral|earth)\b",
    re.IGNORECASE,
)


def _extract_preferences(utterance: str) -> tuple[Optional[str], list[str]]:
    """Return (style, [colors]) extracted from the utterance, or (None, []) if none found."""
    style: Optional[str] = None
    colors: list[str] = []

    m = _STYLE_RE.search(utterance)
    if m:
        style = m.group(1).lower()

    if _COLOR_CONTEXT_RE.search(utterance):
        colors = [m.group(1).lower() for m in _COLOR_FIND_RE.finditer(utterance)]

    return style, colors


def _extract_budget(utterance: str) -> Optional[float]:
    """Return a budget amount (USD) if the utterance states one, else None."""
    m = _BUDGET_RE.search(utterance)
    if not m:
        return None
    raw = next(g for g in m.groups() if g is not None)
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None
