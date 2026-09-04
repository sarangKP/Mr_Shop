"""Purchase tool — mocked buy / price-check flow."""

import random
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


def purchase(item: str, state: dict) -> dict:
    """
    Initiate a mocked purchase for *item* and record it in session state.

    Args:
        item:  The resolved item the user wants to buy (e.g. "navy blazer").
        state: Live session_state dict; a "cart" key is created/appended to.

    Returns:
        {
            "status": "purchase_initiated",
            "item": item,
            "price_usd": float,
            "cart": [str, ...],   # full cart after this purchase
        }
    """
    price = _MOCK_PRICES.get(item.lower(), _DEFAULT_PRICE)

    session.add_to_cart(state, item)
    session.set_last_mentioned_item(state, item)

    return {
        "status": "purchase_initiated",
        "item": item,
        "price_usd": price,
        "cart": list(state["cart"]),
    }


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
    run=lambda utterance, resolved_item, state: purchase(resolved_item or utterance, state),
))
