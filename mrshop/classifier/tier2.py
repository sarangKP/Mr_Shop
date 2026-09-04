"""
Tier 2 intent classifier — embedding similarity via all-MiniLM-L6-v2 (PRD §7).

Falls back from Tier 1. Encodes the utterance and compares it against a small
set of representative sentences per intent (the "taxonomy"). Returns the intent
with the highest cosine similarity if it clears the threshold.

Taxonomy sentences are read from the tool registry at load_model() time — adding
a new intent's examples means registering them in the tool file, not editing here.
The "unclear" catch-all is hardcoded here since it has no corresponding tool.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

# Similarity score below which we don't trust Tier 2 and fall through to
# clarifying questions (or Tier 3 if LLM is enabled).
# Tuned empirically: short possession phrases ("I have a navy blazer") score ~0.34
# against the wardrobe taxonomy; 0.33 captures those without pulling in noise.
DEFAULT_THRESHOLD = 0.33

# Taxonomy sentences for the "unclear" catch-all — no corresponding tool, so
# hardcoded here rather than in the registry.
_UNCLEAR_EXAMPLES = [
    "I'm not sure what I want",
    "Just browsing",
    "Hello, how are you",
    "Thanks for the help",
    "Okay",
    "Never mind",
]

# ---------------------------------------------------------------------------
# Module-level cache — populated by load_model().
# ---------------------------------------------------------------------------

_model = None                  # SentenceTransformer instance
_taxonomy_embeddings: dict[str, np.ndarray] = {}   # intent → (N, D) array


def load_model() -> None:
    """
    Load the SentenceTransformer model and pre-compute taxonomy embeddings.

    Called once at startup (from mrshop/config.py).  Subsequent calls are
    no-ops — the cached model and embeddings are reused.
    """
    global _model, _taxonomy_embeddings
    if _model is not None:
        return  # already loaded

    from sentence_transformers import SentenceTransformer
    from mrshop.tools.registry import all_tools
    _model = SentenceTransformer("all-MiniLM-L6-v2")

    # Build taxonomy from the tool registry + hardcoded "unclear" examples.
    taxonomy: dict[str, list[str]] = {t.intent: t.tier2_examples for t in all_tools()}
    taxonomy["unclear"] = _UNCLEAR_EXAMPLES

    for intent, sentences in taxonomy.items():
        _taxonomy_embeddings[intent] = _model.encode(
            sentences,
            convert_to_numpy=True,
            normalize_embeddings=True,   # unit vectors → dot product = cosine similarity
        )


def _cosine_similarity(vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Return cosine similarity between a single vector and each row of matrix.

    Both inputs are expected to be already L2-normalised (from encode with
    normalize_embeddings=True), so this is just a dot product.
    """
    return matrix @ vec  # shape (N,)


def classify(
    utterance: str,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[Optional[str], float]:
    """
    Embed *utterance* and return the nearest intent above *threshold*.

    Must call load_model() before calling this.

    Returns:
        (intent, best_score)  — intent is the top match if score >= threshold
        (None,  best_score)   — no intent cleared the threshold; caller decides
    """
    if _model is None:
        raise RuntimeError("Tier 2 model not loaded — call load_model() first.")

    vec = _model.encode(
        utterance,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )

    best_intent: Optional[str] = None
    best_score: float = -1.0

    for intent, emb_matrix in _taxonomy_embeddings.items():
        # Max similarity across all taxonomy sentences for this intent.
        scores = _cosine_similarity(vec, emb_matrix)
        score = float(scores.max())
        if score > best_score:
            best_score = score
            best_intent = intent

    if best_score >= threshold:
        return best_intent, best_score
    return None, best_score
