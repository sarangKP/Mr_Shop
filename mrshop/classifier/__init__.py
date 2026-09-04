"""
Classifier package — three-tier hybrid intent detection (PRD §7).

Tier 1: keyword/regex rules         → instant, free       (Step 4)
Tier 2: embedding similarity        → CPU, <100ms         (Step 5)
Tier 3: local LLM (Ollama)          → slower, optional    (Step 9)

resolve_reference: clean interface for slot/reference resolution,
heuristic implementation first (Step 6), LLM implementation in Step 9.
"""
