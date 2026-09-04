"""Purchase tool — mocked buy / price-check flow."""

import re
from mrshop.memory import session
from mrshop.tools.registry import ToolDefinition, register

# Mocked price catalogue — a real implementation would call a product API.
_MOCK_PRICES: dict[str, float] = {
    "navy blazer": 189.99,
    "white t-shirt": 29.99,
    "dark jeans": 79.99,
    "leather loafers": 149.99,
    "chelsea boots": 129.99,
}
_DEFAULT_PRICE = 99.99

_BULK_REF_RE = re.compile(
    r"\b(those|them|these|all of them|the ones|those items|these items)\b",
    re.IGNORECASE,
)


def purchase(item: str, state: dict) -> dict:
    """
    Initiate a mocked purchase for *item* and record it in session state.

    Returns already_owned (without touching the cart) if the item is in the wardrobe.
    """
    wardrobe = session.get(state, "wardrobe_items")
    if item in wardrobe:
        return {
            "status": "already_owned",
            "item": item,
            "message": f"{item!r} is already in your wardrobe — no need to buy it again.",
        }

    price = _MOCK_PRICES.get(item.lower(), _DEFAULT_PRICE)
    session.add_to_cart(state, item)
    session.add_wardrobe_item(state, item)
    session.set_last_mentioned_item(state, item)

    return {
        "status": "purchase_initiated",
        "item": item,
        "price_usd": price,
        "cart": list(state["cart"]),
        "wardrobe_items": list(state["wardrobe_items"]),
    }


def _run_purchase(utterance: str, resolved_item, state: dict) -> dict:
    # Bulk reference ("those items", "them") + suggestions available → buy all non-wardrobe suggested items.
    if _BULK_REF_RE.search(utterance or ""):
        suggested = session.get(state, "last_suggested_items")
        wardrobe = session.get(state, "wardrobe_items")
        if suggested:
            items_to_buy = [item for item in suggested if item not in wardrobe]
            results = [purchase(item, state) for item in items_to_buy]
            purchased = [r["item"] for r in results if r.get("status") == "purchase_initiated"]
            session.clear_cart(state)
            return {
                "status": "bulk_purchase",
                "items_purchased": purchased,
                "results": results,
                "cart": [],
            }

    if resolved_item:
        result = purchase(resolved_item, state)
        if result.get("status") == "purchase_initiated":
            session.clear_cart(state)
            result["cart"] = []
        return result

    return {}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

register(ToolDefinition(
    intent="purchase",
    tier1_priority=40,
    tier1_patterns=[
        r"\b(want to (buy|purchase|order)|looking to (buy|purchase|order))\b",
        r"\bcan i (buy|get|order|purchase)\b",
        r"\bhow much (does|is|would|will|do)\b",
        r"\b(price|cost|pricing) (of|for|check)\b",
        r"\badd (it|this|that) to (my )?(cart|bag|basket)\b",
        r"\b(buy|purchase) (it|this|that|one|the)\b",
        r"\bi('d| would) like to (buy|purchase|order)\b",
    ],
    tier2_examples=[
        "I want to buy this clothing item",
        "How much does this item cost?",
        "I would like to purchase this",
        "What is the price of this?",
        "I'm interested in buying this piece",
        "Where can I get this?",
    ],
    llm_instruction=(
        "Confirm the purchase intent, mention the price, and acknowledge the cart. "
        "If you assumed an item, say so naturally. 1–2 sentences."
    ),
    run=_run_purchase,
))
