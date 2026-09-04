"""Styling advice tool — returns mocked outfit suggestions."""

from mrshop.memory import session
from mrshop.tools.registry import ToolDefinition, register

# Mocked suggestion templates keyed by a rough category derived from the query.
# Real implementation would call a fashion-aware model; for now this is enough
# to exercise the full pipeline end-to-end.
_SUGGESTIONS = {
    "jeans": [
        "White Oxford shirt + leather loafers",
        "Navy blazer + white t-shirt + white sneakers",
        "Chunky knit sweater + Chelsea boots",
    ],
    "blazer": [
        "Slim chinos + loafers + pocket square",
        "Dark jeans + plain tee + white sneakers",
        "Tailored trousers + turtleneck",
    ],
    "default": [
        "Classic white shirt + well-fitted trousers",
        "Neutral-toned layers — works for most pieces",
        "Monochrome outfit with one contrasting accessory",
    ],
}


def styling_advice(query: str, state: dict) -> dict:
    """
    Return mocked styling suggestions for *query*, aware of the user's wardrobe.

    Args:
        query: What the user asked about (e.g. "what goes with dark blue jeans?").
        state: Live session_state dict; wardrobe_items read to surface relevant pieces.

    Returns:
        {
            "suggestions": [str, ...],
            "based_on_wardrobe": [str, ...],   # wardrobe items referenced
            "query": str,
        }
    """
    wardrobe = session.get(state, "wardrobe_items")

    # Pick a suggestion list based on a keyword in the query.
    lower = query.lower()
    if "jean" in lower or "denim" in lower:
        key = "jeans"
    elif "blazer" in lower or "jacket" in lower:
        key = "blazer"
    else:
        key = "default"

    # Surface any wardrobe items that are relevant to the query.
    relevant = [item for item in wardrobe if any(w in lower for w in item.lower().split())]

    return {
        "suggestions": _SUGGESTIONS[key],
        "based_on_wardrobe": relevant,
        "query": query,
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

register(ToolDefinition(
    intent="styling_advice",
    tier1_priority=50,
    tier1_patterns=[
        r"\bwhat (goes|works|pairs?) with\b",
        r"\bwhat (should i|can i|would you) (wear|put on|combine)\b",
        r"\bhow (should i|do i|can i|to) (wear|style|dress|pair)\b",
        r"\bwhat to wear\b",
        r"\b(outfit|look) (ideas?|suggestions?|recommendations?|inspo|inspiration)\b",
        r"\b(suggest|recommend).{0,20}(outfit|wear|style|look)\b",
        r"\bstyle (advice|tips?|guide|suggestions?|recommendations?)\b",
        r"\bwhat (outfit|look|style) (should|would|do)\b",
        r"\bhow do i look\b",
    ],
    tier2_examples=[
        "What outfit goes with this piece?",
        "How should I style this clothing item?",
        "Give me fashion advice for what to wear",
        "Suggest an outfit combination for me",
        "I need help putting together a look",
        "What should I wear to look good?",
    ],
    llm_instruction=(
        "Present the styling suggestions naturally. Reference the user's wardrobe "
        "items if relevant. 2–3 sentences, friendly tone."
    ),
    run=lambda utterance, resolved_item, state: styling_advice(utterance, state),
))
