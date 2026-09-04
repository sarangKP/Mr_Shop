"""
Tests for Tier 1 (keyword/regex) and Tier 2 (embedding) intent classification.

Tier 1 tests cover:
  - clear positive hits that keyword rules MUST catch
  - boundary cases that Tier 1 must NOT mis-fire on (left to Tier 2)

Tier 2 tests cover:
  - ambiguous phrasings that Tier 1 correctly misses
  - that the embedding model resolves them semantically
  - threshold behaviour
  - the model loads and pre-computes embeddings exactly once (session fixture)
"""

import pytest
from mrshop.classifier.tier1 import classify, get_intents
from mrshop.tools.registry import get_intents as registry_intents


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_intent(utterance: str, expected: str):
    intent, confidence = classify(utterance)
    assert intent == expected, (
        f"Expected {expected!r} but got {intent!r} for: {utterance!r}"
    )
    assert confidence == 1.0


def assert_miss(utterance: str):
    """Tier 1 should return (None, 0.0) — let Tier 2 handle it."""
    intent, confidence = classify(utterance)
    assert intent is None, (
        f"Expected Tier 1 miss but got {intent!r} for: {utterance!r}"
    )
    assert confidence == 0.0


# ---------------------------------------------------------------------------
# INTENTS constant
# ---------------------------------------------------------------------------

def test_intents_contains_all_expected():
    assert set(get_intents()) == {"wardrobe_upload", "wardrobe_list", "styling_advice", "purchase", "booking", "unclear"}


# ---------------------------------------------------------------------------
# wardrobe_upload — clear hits
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", [
    "I just got a navy blazer",
    "just got a new white t-shirt",
    "I just bought some dark jeans",
    "just picked up a leather jacket",
    "I recently got some chelsea boots",
    "I recently bought a new coat",
    "I picked up a new scarf yesterday",
    "adding this to my wardrobe",
    "I added it to my wardrobe",
])
def test_wardrobe_upload_clear_hits(utterance):
    assert_intent(utterance, "wardrobe_upload")


# ---------------------------------------------------------------------------
# wardrobe_upload — must NOT steal from purchase
# "I just bought" is wardrobe context, but "I want to buy" is purchase.
# ---------------------------------------------------------------------------

def test_wardrobe_upload_does_not_match_want_to_buy():
    assert_intent("I want to buy a jacket", "purchase")

def test_wardrobe_upload_does_not_match_can_i_buy():
    assert_intent("can I buy that jacket?", "purchase")


# ---------------------------------------------------------------------------
# purchase — clear hits
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", [
    "I want to buy that jacket",
    "can I buy that jacket?",
    "can I get that coat?",
    "how much does the blazer cost?",
    "how much is this jacket?",
    "how much would that be?",
    "what's the price of this shirt?",
    "I'd like to purchase this",
    "I would like to order this coat",
    "looking to buy a new blazer",
    "add it to my cart",
    "add this to my bag",
    "buy it",
    "purchase this one",
])
def test_purchase_clear_hits(utterance):
    assert_intent(utterance, "purchase")


# ---------------------------------------------------------------------------
# booking — clear hits
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", [
    "book me a stylist call Friday",
    "book me a stylist appointment",
    "I want to book a consultation",
    "schedule a stylist session for me",
    "can you arrange a stylist call?",
    "I'd like a style consultation",
    "book me a slot with a stylist",
    "stylist call on Monday",
    "stylist session next week",
])
def test_booking_clear_hits(utterance):
    assert_intent(utterance, "booking")


# ---------------------------------------------------------------------------
# styling_advice — clear hits
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", [
    "what goes with dark blue jeans?",
    "what works with a navy blazer?",
    "what pairs with this jacket?",
    "what should I wear with this?",
    "how should I wear this blazer?",
    "how do I style dark jeans?",
    "what to wear today?",
    "outfit ideas for a business casual look",
    "outfit suggestions please",
    "style advice for a wedding",
    "style tips for smart casual",
    "suggest an outfit for me",
    "recommend a look for tonight",
    "what outfit should I go with?",
    "not sure what to wear to the interview",   # "what to wear" triggers the rule
])
def test_styling_advice_clear_hits(utterance):
    assert_intent(utterance, "styling_advice")


# ---------------------------------------------------------------------------
# Tier 1 misses — ambiguous utterances that MUST fall through to Tier 2.
# These are phrasings where a keyword hit would be wrong or too noisy.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", [
    # Vague — no clear keyword signal
    "I'm not sure what to do",
    "hello there",
    "thanks!",
    "that's nice",
    # Ambiguous — could be multiple intents; Tier 2 resolves via semantics
    "I have a navy blazer",          # possession, but could be context-setting
    "tell me about jackets",         # no clear intent keyword
    "what do you think about this?", # vague
    "help me",                       # no intent keyword
])
def test_tier1_miss_on_ambiguous(utterance):
    assert_miss(utterance)


# ---------------------------------------------------------------------------
# Case insensitivity
# ---------------------------------------------------------------------------

def test_case_insensitive_wardrobe():
    assert_intent("JUST GOT A NEW JACKET", "wardrobe_upload")

def test_case_insensitive_purchase():
    assert_intent("HOW MUCH IS THIS?", "purchase")

def test_case_insensitive_styling():
    assert_intent("WHAT GOES WITH DARK JEANS?", "styling_advice")


# ---------------------------------------------------------------------------
# Return type contract
# ---------------------------------------------------------------------------

def test_hit_returns_float_one():
    _, confidence = classify("what goes with dark jeans?")
    assert confidence == 1.0
    assert isinstance(confidence, float)

def test_miss_returns_float_zero():
    _, confidence = classify("hello there")
    assert confidence == 0.0
    assert isinstance(confidence, float)

def test_hit_intent_is_in_intents_list():
    intent, _ = classify("I want to buy a jacket")
    assert intent in get_intents()


# ===========================================================================
# Tier 2 — embedding similarity (all-MiniLM-L6-v2)
# ===========================================================================

import pytest
from mrshop.classifier.tier2 import classify as t2_classify, load_model, DEFAULT_THRESHOLD


@pytest.fixture(scope="session", autouse=True)
def load_embedding_model():
    """Load the model once for the whole test session (takes ~2s first run)."""
    load_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_t2_intent(utterance: str, expected: str, threshold: float = DEFAULT_THRESHOLD):
    """Tier 1 must miss AND Tier 2 must resolve to expected intent."""
    t1_intent, _ = classify(utterance)
    assert t1_intent is None, (
        f"Tier 1 unexpectedly caught {utterance!r} as {t1_intent!r} — "
        "move it to the Tier 1 test section"
    )
    t2_intent, score = t2_classify(utterance, threshold=threshold)
    assert t2_intent == expected, (
        f"Tier 2: expected {expected!r} but got {t2_intent!r} "
        f"(score={score:.3f}) for: {utterance!r}"
    )


# ---------------------------------------------------------------------------
# Ambiguous phrasings — Tier 1 misses, Tier 2 resolves
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("utterance", [
    "I have a navy blazer",           # ownership phrasing without "just got"
    "I own a leather jacket",         # explicit ownership, no acquisition signal
    "I've got a white shirt",         # colloquial possession
    "I keep a blazer in my closet",   # wardrobe description
])
def test_t2_wardrobe_upload_ambiguous(utterance):
    assert_t2_intent(utterance, "wardrobe_upload")


@pytest.mark.parametrize("utterance", [
    "I need help with an outfit",                  # no "what goes with" trigger
    "looking for something smart casual",           # no advice keyword
    "I want to look good for a dinner",            # intent implied, not stated
    "I have no idea what to put on",               # no direct keyword
])
def test_t2_styling_advice_ambiguous(utterance):
    assert_t2_intent(utterance, "styling_advice")


@pytest.mark.parametrize("utterance", [
    "is that affordable?",             # price concern, no "how much"
    "I'm interested in getting one",   # purchase intent, indirect phrasing
    "where can I find this?",          # shopping intent
])
def test_t2_purchase_ambiguous(utterance):
    assert_t2_intent(utterance, "purchase")


@pytest.mark.parametrize("utterance", [
    "I need a stylist's opinion",           # consultation intent, no "book" keyword
    "I want to meet with a fashion expert", # meeting intent, no "book" keyword
    "I need personal help from a stylist",  # direct stylist request, no schedule word
])
def test_t2_booking_ambiguous(utterance):
    assert_t2_intent(utterance, "booking")


# ---------------------------------------------------------------------------
# Threshold behaviour
# ---------------------------------------------------------------------------

def test_t2_very_high_threshold_returns_none():
    """With threshold > 1.0 (impossible for cosine similarity) nothing resolves."""
    intent, _ = t2_classify("I have a blazer", threshold=1.01)
    assert intent is None


def test_t2_zero_threshold_always_returns_something():
    """With threshold=0 we always get the nearest intent, even for gibberish."""
    intent, score = t2_classify("asdfghjkl qwerty", threshold=0.0)
    assert intent is not None
    assert intent in get_intents()


def test_t2_score_is_float_between_0_and_1():
    intent, score = t2_classify("I want to buy a jacket")
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_t2_clear_utterance_above_default_threshold():
    """Unambiguous phrasings should exceed the default threshold easily."""
    intent, score = t2_classify("I want to buy a jacket")
    assert score >= DEFAULT_THRESHOLD
    assert intent == "purchase"


# ---------------------------------------------------------------------------
# load_model idempotency
# ---------------------------------------------------------------------------

def test_load_model_is_idempotent():
    """Calling load_model() twice must not raise or reload."""
    from mrshop.classifier import tier2
    model_before = tier2._model
    load_model()
    assert tier2._model is model_before  # same object, not reloaded
