"""
Session state schema and read/write helpers (PRD §8).

All orchestrator and tool code goes through these helpers rather than
poking the dict directly — makes the shape of memory explicit and keeps
mutation in one place.

The state dict is intentionally plain (no class, no property magic) so it
stays trivially serialisable and easy to inspect in the terminal trace.
"""

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def new_session() -> dict:
    """Return a fresh session_state dict matching the PRD §8 schema."""
    return {
        "wardrobe_items": [],
        "preferences": {"style": None, "colors": []},
        "gender": None,               # "male" | "female" | None
        "budget": None,
        "cart": [],                   # items added via purchase tool
        "current_topic": None,        # set on first classified turn
        "topic_history": [],          # list of past topics, oldest first
        "last_mentioned_item": None,  # used by heuristic reference resolver
        "last_suggested_items": [],   # items suggested in the most recent styling turn
        "pending_action": None,       # reserved for multi-turn confirmations
    }


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def get(state: dict, key: str) -> Any:
    """Read a top-level key from session state."""
    if key not in state:
        raise KeyError(f"Unknown session state key: {key!r}")
    return state[key]


def snapshot(state: dict) -> dict:
    """Return a deep copy of state — safe to log or compare in tests."""
    return copy.deepcopy(state)


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def update(state: dict, **kwargs) -> None:
    """
    Write one or more top-level keys into session state in place.

    Raises KeyError for unrecognised keys so callers can't silently invent
    new top-level fields and fragment the schema.
    """
    for key in kwargs:
        if key not in state:
            raise KeyError(f"Unknown session state key: {key!r}")
    state.update(kwargs)


def switch_topic(state: dict, new_topic: str) -> None:
    """
    Move current_topic → topic_history and set new_topic as current.

    Does NOT wipe any other state — wardrobe items, preferences, budget, and
    last_mentioned_item all survive the switch so the user can pivot back
    without re-explaining context (PRD §8).
    """
    current = state["current_topic"]
    if current is not None and current != new_topic:
        state["topic_history"].append(current)
    state["current_topic"] = new_topic


def add_wardrobe_item(state: dict, item: str) -> None:
    """Append *item* to wardrobe_items (no-op if item already present)."""
    if item not in state["wardrobe_items"]:
        state["wardrobe_items"].append(item)


def set_last_mentioned_item(state: dict, item: str | None) -> None:
    """Record the most recently referenced clothing item."""
    state["last_mentioned_item"] = item


def set_gender(state: dict, gender: str) -> None:
    """Record the user's gender identity (only updates if currently unknown)."""
    if state.get("gender") is None:
        state["gender"] = gender


def set_budget(state: dict, amount: float) -> None:
    """Record the user's stated budget in USD."""
    state["budget"] = amount


def add_to_cart(state: dict, item: str) -> None:
    """Append *item* to the cart (no dedup — same item can be bought multiple times)."""
    state["cart"].append(item)


def set_last_suggested_items(state: dict, items: list[str]) -> None:
    """Replace last_suggested_items with the new list from the latest styling turn."""
    state["last_suggested_items"] = list(items)


def update_preferences(state: dict, style: str | None = None, colors: list | None = None) -> None:
    """
    Merge new preference values into the existing preferences dict.

    Passing None for a field leaves it unchanged.
    Colors are merged (union), not replaced, so earlier colour preferences
    are preserved across topic switches.
    """
    if style is not None:
        state["preferences"]["style"] = style
    if colors is not None:
        existing = set(state["preferences"]["colors"])
        state["preferences"]["colors"] = list(existing | set(colors))
