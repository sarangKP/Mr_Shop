"""Booking tool — mocked stylist-consultation scheduling."""

from mrshop.memory import session
from mrshop.tools.registry import ToolDefinition, register

_MOCK_STYLISTS = ["Alex", "Jordan", "Morgan"]
_DEFAULT_STYLIST = "Alex"


def booking(details: str, state: dict) -> dict:
    """
    Schedule a mocked stylist consultation.

    Args:
        details: Raw time/date string from the user (e.g. "Friday afternoon").
        state:   Live session_state dict; read-only in this tool.

    Returns:
        {
            "status": "booked",
            "slot": str,      # echoes back the requested slot
            "stylist": str,   # mocked stylist name
            "confirmation": str,
        }
    """
    # In a real system this would call a calendar API and return a real slot.
    stylist = _DEFAULT_STYLIST
    confirmation_id = f"MRSHOP-{abs(hash(details)) % 100000:05d}"

    return {
        "status": "booked",
        "slot": details,
        "stylist": stylist,
        "confirmation": confirmation_id,
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

register(ToolDefinition(
    intent="booking",
    tier1_priority=30,
    tier1_patterns=[
        r"\b(stylist call|stylist session|style consultation|styling session)\b",
        r"\bbook (me )?(a |an )?(stylist|appointment|consultation|call|session)\b",
        r"\b(schedule|reserve|arrange).{0,30}(stylist|appointment|consultation|call|session)\b",
        r"\b(stylist|consultation|appointment).{0,30}(book|schedule|reserve|arrange)\b",
        r"\bbook\b.{0,25}(stylist|appointment|call|session|slot|time)\b",
    ],
    tier2_examples=[
        "I want to schedule a stylist appointment",
        "Book me a consultation with a fashion expert",
        "I would like to reserve time with a stylist",
        "Set up a styling session for me",
        "I need to see a personal stylist",
        "Arrange a meeting with a style consultant",
    ],
    llm_instruction=(
        "Confirm the booking. Mention the stylist, the slot, and the confirmation "
        "code. 1–2 sentences."
    ),
    run=lambda utterance, resolved_item, state: booking(utterance, state),
))
