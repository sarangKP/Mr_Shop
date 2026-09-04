"""
Unit tests for the memory layer (mrshop/memory/session.py).

Every test is self-contained — no fixtures, no mocks, no I/O.
"""

import pytest
from mrshop.memory.session import (
    new_session,
    get,
    update,
    switch_topic,
    add_wardrobe_item,
    add_to_cart,
    clear_cart,
    set_last_mentioned_item,
    set_last_suggested_items,
    update_preferences,
    snapshot,
)


# ---------------------------------------------------------------------------
# new_session
# ---------------------------------------------------------------------------

def test_new_session_has_all_required_keys():
    state = new_session()
    required = {
        "wardrobe_items", "preferences", "gender", "budget", "cart",
        "current_topic", "topic_history", "last_mentioned_item",
        "last_suggested_items", "pending_action",
    }
    assert required == set(state.keys())


def test_new_session_defaults():
    state = new_session()
    assert state["wardrobe_items"] == []
    assert state["cart"] == []
    assert state["topic_history"] == []
    assert state["current_topic"] is None
    assert state["last_mentioned_item"] is None
    assert state["budget"] is None
    assert state["pending_action"] is None
    assert state["preferences"] == {"style": None, "colors": []}


def test_new_session_returns_independent_copies():
    # Mutating one session must not affect another.
    s1 = new_session()
    s2 = new_session()
    s1["wardrobe_items"].append("red scarf")
    assert s2["wardrobe_items"] == []


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

def test_get_returns_value():
    state = new_session()
    state["budget"] = 200
    assert get(state, "budget") == 200


def test_get_unknown_key_raises():
    state = new_session()
    with pytest.raises(KeyError):
        get(state, "nonexistent_field")


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

def test_update_single_key():
    state = new_session()
    update(state, budget=150)
    assert state["budget"] == 150


def test_update_multiple_keys():
    state = new_session()
    update(state, budget=100, pending_action="confirm_purchase")
    assert state["budget"] == 100
    assert state["pending_action"] == "confirm_purchase"


def test_update_unknown_key_raises():
    state = new_session()
    with pytest.raises(KeyError):
        update(state, invented_key="oops")


# ---------------------------------------------------------------------------
# switch_topic
# ---------------------------------------------------------------------------

def test_switch_topic_sets_current():
    state = new_session()
    switch_topic(state, "styling_advice")
    assert state["current_topic"] == "styling_advice"


def test_switch_topic_parks_old_topic():
    state = new_session()
    switch_topic(state, "styling_advice")
    switch_topic(state, "purchase")
    assert state["current_topic"] == "purchase"
    assert "styling_advice" in state["topic_history"]


def test_switch_topic_does_not_wipe_wardrobe():
    """Core 'park, don't wipe' invariant from PRD §8."""
    state = new_session()
    add_wardrobe_item(state, "navy blazer")
    switch_topic(state, "styling_advice")
    switch_topic(state, "purchase")
    assert "navy blazer" in state["wardrobe_items"]


def test_switch_topic_does_not_wipe_last_mentioned_item():
    """Reference resolver relies on this surviving topic switches."""
    state = new_session()
    set_last_mentioned_item(state, "navy blazer")
    switch_topic(state, "styling_advice")
    switch_topic(state, "purchase")
    assert state["last_mentioned_item"] == "navy blazer"


def test_switch_topic_same_topic_no_duplicate_history():
    """Switching to the same topic should not append to history."""
    state = new_session()
    switch_topic(state, "styling_advice")
    switch_topic(state, "styling_advice")
    assert state["topic_history"].count("styling_advice") == 0


def test_switch_topic_records_full_history():
    state = new_session()
    for topic in ("styling_advice", "purchase", "booking"):
        switch_topic(state, topic)
    # topic_history should have the first two; current is "booking"
    assert state["topic_history"] == ["styling_advice", "purchase"]
    assert state["current_topic"] == "booking"


# ---------------------------------------------------------------------------
# add_wardrobe_item
# ---------------------------------------------------------------------------

def test_add_wardrobe_item_appends():
    state = new_session()
    add_wardrobe_item(state, "white t-shirt")
    assert "white t-shirt" in state["wardrobe_items"]


def test_add_wardrobe_item_no_duplicates():
    state = new_session()
    add_wardrobe_item(state, "white t-shirt")
    add_wardrobe_item(state, "white t-shirt")
    assert state["wardrobe_items"].count("white t-shirt") == 1


def test_add_multiple_wardrobe_items():
    state = new_session()
    for item in ("navy blazer", "white t-shirt", "dark jeans"):
        add_wardrobe_item(state, item)
    assert len(state["wardrobe_items"]) == 3


# ---------------------------------------------------------------------------
# set_last_mentioned_item
# ---------------------------------------------------------------------------

def test_set_last_mentioned_item():
    state = new_session()
    set_last_mentioned_item(state, "navy blazer")
    assert state["last_mentioned_item"] == "navy blazer"


def test_set_last_mentioned_item_can_be_cleared():
    state = new_session()
    set_last_mentioned_item(state, "navy blazer")
    set_last_mentioned_item(state, None)
    assert state["last_mentioned_item"] is None


# ---------------------------------------------------------------------------
# update_preferences
# ---------------------------------------------------------------------------

def test_update_preferences_style():
    state = new_session()
    update_preferences(state, style="smart casual")
    assert state["preferences"]["style"] == "smart casual"


def test_update_preferences_colors_merged_not_replaced():
    state = new_session()
    update_preferences(state, colors=["navy", "white"])
    update_preferences(state, colors=["black"])
    colors = set(state["preferences"]["colors"])
    assert colors == {"navy", "white", "black"}


def test_update_preferences_none_args_leave_existing():
    state = new_session()
    update_preferences(state, style="streetwear")
    update_preferences(state, colors=["grey"])  # style not passed
    assert state["preferences"]["style"] == "streetwear"


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------

def test_snapshot_is_deep_copy():
    state = new_session()
    add_wardrobe_item(state, "red scarf")
    snap = snapshot(state)
    state["wardrobe_items"].append("blue coat")
    assert "blue coat" not in snap["wardrobe_items"]


# ---------------------------------------------------------------------------
# last_suggested_items
# ---------------------------------------------------------------------------

def test_new_session_has_last_suggested_items_key():
    state = new_session()
    assert "last_suggested_items" in state
    assert state["last_suggested_items"] == []


def test_set_last_suggested_items_stores_list():
    state = new_session()
    set_last_suggested_items(state, ["white shirt", "trousers"])
    assert get(state, "last_suggested_items") == ["white shirt", "trousers"]


def test_set_last_suggested_items_replaces_previous():
    state = new_session()
    set_last_suggested_items(state, ["blazer"])
    set_last_suggested_items(state, ["white shirt", "trousers"])
    assert get(state, "last_suggested_items") == ["white shirt", "trousers"]


# ---------------------------------------------------------------------------
# clear_cart
# ---------------------------------------------------------------------------

def test_clear_cart_empties_cart():
    state = new_session()
    add_to_cart(state, "navy blazer")
    add_to_cart(state, "white shirt")
    clear_cart(state)
    assert get(state, "cart") == []


def test_clear_cart_on_empty_cart_is_noop():
    state = new_session()
    clear_cart(state)
    assert get(state, "cart") == []
