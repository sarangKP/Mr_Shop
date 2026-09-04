"""
Unit tests for the tool layer (mrshop/tools/).

All tools take plain data + a session_state dict and return plain dicts.
No mocking needed — state is constructed directly with new_session().
"""

from mrshop.memory.session import new_session, get, add_wardrobe_item, set_last_mentioned_item
from mrshop.tools.wardrobe import wardrobe_upload
from mrshop.tools.styling import styling_advice
from mrshop.tools.purchase import purchase
from mrshop.tools.booking import booking


# ---------------------------------------------------------------------------
# wardrobe_upload
# ---------------------------------------------------------------------------

def test_wardrobe_upload_adds_item():
    state = new_session()
    result = wardrobe_upload("navy blazer", state)
    assert result["status"] == "added"
    assert result["item"] == "navy blazer"
    assert "navy blazer" in get(state, "wardrobe_items")


def test_wardrobe_upload_reports_wardrobe_size():
    state = new_session()
    wardrobe_upload("navy blazer", state)
    result = wardrobe_upload("white t-shirt", state)
    assert result["wardrobe_size"] == 2


def test_wardrobe_upload_duplicate_returns_already_owned():
    state = new_session()
    wardrobe_upload("navy blazer", state)
    result = wardrobe_upload("navy blazer", state)
    assert result["status"] == "already_owned"
    # Still only one copy in the wardrobe.
    assert get(state, "wardrobe_items").count("navy blazer") == 1


def test_wardrobe_upload_sets_last_mentioned_item():
    state = new_session()
    wardrobe_upload("navy blazer", state)
    assert get(state, "last_mentioned_item") == "navy blazer"


# ---------------------------------------------------------------------------
# styling_advice
# ---------------------------------------------------------------------------

def test_styling_advice_returns_suggestions():
    state = new_session()
    result = styling_advice("what goes with dark blue jeans?", state)
    assert "suggestions" in result
    assert len(result["suggestions"]) > 0


def test_styling_advice_includes_query():
    state = new_session()
    query = "what goes with dark blue jeans?"
    result = styling_advice(query, state)
    assert result["query"] == query


def test_styling_advice_surfaces_relevant_wardrobe_items():
    state = new_session()
    add_wardrobe_item(state, "navy blazer")
    add_wardrobe_item(state, "white t-shirt")
    result = styling_advice("how should I style my blazer?", state)
    # "blazer" appears in the wardrobe item — should be surfaced
    assert "navy blazer" in result["based_on_wardrobe"]


def test_styling_advice_empty_wardrobe():
    state = new_session()
    result = styling_advice("what should I wear today?", state)
    assert result["based_on_wardrobe"] == []


def test_styling_advice_jeans_query_picks_jeans_suggestions():
    state = new_session()
    result = styling_advice("what goes with my jeans?", state)
    # Jeans suggestions mention specific pairings — spot-check one keyword.
    combined = " ".join(result["suggestions"]).lower()
    assert "shirt" in combined or "sneakers" in combined or "boots" in combined


# ---------------------------------------------------------------------------
# purchase
# ---------------------------------------------------------------------------

def test_purchase_returns_purchase_initiated():
    state = new_session()
    result = purchase("navy blazer", state)
    assert result["status"] == "purchase_initiated"
    assert result["item"] == "navy blazer"


def test_purchase_returns_price():
    state = new_session()
    result = purchase("navy blazer", state)
    assert isinstance(result["price_usd"], float)
    assert result["price_usd"] > 0


def test_purchase_known_item_has_mock_price():
    state = new_session()
    result = purchase("navy blazer", state)
    assert result["price_usd"] == 189.99


def test_purchase_creates_cart():
    state = new_session()
    purchase("navy blazer", state)
    assert "cart" in state
    assert "navy blazer" in state["cart"]


def test_purchase_accumulates_cart():
    state = new_session()
    purchase("navy blazer", state)
    purchase("white t-shirt", state)
    assert len(state["cart"]) == 2


def test_purchase_sets_last_mentioned_item():
    state = new_session()
    purchase("navy blazer", state)
    assert get(state, "last_mentioned_item") == "navy blazer"


# ---------------------------------------------------------------------------
# booking
# ---------------------------------------------------------------------------

def test_booking_returns_booked():
    state = new_session()
    result = booking("Friday afternoon", state)
    assert result["status"] == "booked"


def test_booking_echoes_slot():
    state = new_session()
    result = booking("Friday afternoon", state)
    assert result["slot"] == "Friday afternoon"


def test_booking_returns_stylist():
    state = new_session()
    result = booking("Friday afternoon", state)
    assert isinstance(result["stylist"], str)
    assert len(result["stylist"]) > 0


def test_booking_returns_confirmation_id():
    state = new_session()
    result = booking("Friday afternoon", state)
    assert result["confirmation"].startswith("MRSHOP-")


def test_booking_different_slots_different_confirmations():
    state = new_session()
    r1 = booking("Friday afternoon", state)
    r2 = booking("Monday morning", state)
    assert r1["confirmation"] != r2["confirmation"]


# ---------------------------------------------------------------------------
# styling_advice — last_suggested_items tracking
# ---------------------------------------------------------------------------

def test_styling_advice_stores_suggested_items_in_session():
    state = new_session()
    styling_advice("what should I wear for a job interview", state)
    suggested = get(state, "last_suggested_items")
    assert isinstance(suggested, list)
    assert len(suggested) > 0


def test_styling_advice_suggested_items_are_strings():
    state = new_session()
    styling_advice("what goes with jeans", state)
    suggested = get(state, "last_suggested_items")
    assert all(isinstance(item, str) for item in suggested)


def test_styling_advice_replaces_previous_suggested_items():
    state = new_session()
    styling_advice("what goes with jeans", state)
    first_suggested = list(get(state, "last_suggested_items"))
    styling_advice("what goes with a blazer", state)
    second_suggested = get(state, "last_suggested_items")
    assert second_suggested != first_suggested


# ---------------------------------------------------------------------------
# purchase — wardrobe guard + bulk purchase
# ---------------------------------------------------------------------------

from mrshop.memory.session import set_last_suggested_items
from mrshop.tools.purchase import _run_purchase


def test_purchase_returns_already_owned_for_wardrobe_item():
    state = new_session()
    add_wardrobe_item(state, "blue shoes")
    result = purchase("blue shoes", state)
    assert result["status"] == "already_owned"
    assert state["cart"] == []


def test_purchase_adds_non_wardrobe_item_to_cart():
    state = new_session()
    result = purchase("white shirt", state)
    assert result["status"] == "purchase_initiated"
    assert "white shirt" in state["cart"]


def test_run_purchase_bulk_buys_suggested_items_excluding_wardrobe():
    state = new_session()
    add_wardrobe_item(state, "blue shoes")
    set_last_suggested_items(state, ["white shirt", "trousers", "blue shoes"])
    result = _run_purchase("i want to purchase those items", None, state)
    assert result["status"] == "bulk_purchase"
    assert "blue shoes" not in state["cart"]
    assert "white shirt" in state["cart"]
    assert "trousers" in state["cart"]


def test_run_purchase_single_resolved_item_when_no_bulk_pronoun():
    state = new_session()
    result = _run_purchase("i want to buy a white shirt", "white shirt", state)
    assert result["status"] == "purchase_initiated"
    assert state["cart"] == ["white shirt"]
