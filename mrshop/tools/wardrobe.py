"""Wardrobe tools — upload (record new item) and list (query current items)."""

from mrshop.memory import session
from mrshop.tools.registry import ToolDefinition, register


def wardrobe_list(state: dict) -> dict:
    """
    Return the current wardrobe contents.

    Returns:
        {"items": [str, ...], "count": int}
    """
    items = list(session.get(state, "wardrobe_items"))
    return {"items": items, "count": len(items)}


def wardrobe_upload(item: str, state: dict) -> dict:
    """
    Add *item* to the user's wardrobe and return a confirmation payload.

    Args:
        item:  Normalised description of the clothing item (e.g. "navy blazer").
        state: Live session_state dict; wardrobe_items is updated in place.

    Returns:
        {"status": "added", "item": item, "wardrobe_size": int}
        {"status": "already_owned", "item": item, "wardrobe_size": int}
    """
    already_owned = item in session.get(state, "wardrobe_items")
    session.add_wardrobe_item(state, item)
    session.set_last_mentioned_item(state, item)

    status = "already_owned" if already_owned else "added"
    return {
        "status": status,
        "item": item,
        "wardrobe_size": len(session.get(state, "wardrobe_items")),
    }


# ---------------------------------------------------------------------------
# Registry — single place to define everything about these two intents
# ---------------------------------------------------------------------------

def _run_wardrobe_upload(utterance: str, resolved_item, state: dict) -> dict:
    return wardrobe_upload(resolved_item or utterance, state)


def _run_wardrobe_list(utterance: str, resolved_item, state: dict) -> dict:
    return wardrobe_list(state)


register(ToolDefinition(
    intent="wardrobe_upload",
    tier1_priority=10,
    tier1_patterns=[
        r"\b(just got|just bought|just picked up|just ordered|recently (got|bought|picked up))\b",
        r"\bi (got|picked up|received) (a |an |my |some )?new\b",
        r"\b(new to my wardrobe|new in my wardrobe|new in my closet|new addition to my)\b",
        r"\b(adding|added) (it |this |that |a |an )?(to my wardrobe|to my closet)\b",
        r"\bi also (have|own|got|bought)\b",
        r"\bi bought (a |an |the |some )?",
    ],
    tier2_examples=[
        "I just got a new piece of clothing",
        "I recently bought something for my wardrobe",
        "I already own this item",
        "This clothing item is already in my possession",
        "I picked up a new garment",
        "This is a new addition to my wardrobe",
        "I already have this in my closet",
        "I've owned this for a while",
        "This garment is mine",
    ],
    llm_instruction=(
        "Acknowledge the wardrobe update warmly. Confirm what was added or note "
        "if it was already owned. 1–2 sentences."
    ),
    use_heuristic_resolver=True,
    run=_run_wardrobe_upload,
))

register(ToolDefinition(
    intent="wardrobe_list",
    tier1_priority=20,
    tier1_patterns=[
        r"\bwhat (do i|have i|items? do i|stuff do i) (have|own|got)\b",
        r"\b(show|list|display) (me |my )?(wardrobe|closet|items?|clothes|inventory)\b",
        r"\bwhat('s| is) in my (wardrobe|closet)\b",
        r"\bwhat (all |else )?(do i|can i) (see|check|find)\b",
        r"\b(all )?(my )?(current )?(wardrobe|closet|items?|clothes) (i have|i own|in total)\b",
    ],
    tier2_examples=[
        "Please show me everything in my wardrobe",
        "List all my clothes",
        "Give me an inventory of my closet",
        "Show me my wardrobe contents",
        "What is currently stored in my closet?",
        "Display my wardrobe summary",
        "Can you list all the garments I own?",
    ],
    llm_instruction=(
        "List the user's wardrobe items conversationally. If the wardrobe is empty, "
        "encourage them to add items. Keep it natural and friendly, not just a raw list."
    ),
    use_heuristic_resolver=True,
    run=_run_wardrobe_list,
))
