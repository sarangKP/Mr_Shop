# Product Requirements Document
## Mr.Shop — Ambient Conversation & Orchestration Layer (Prototype)

**Status:** Draft
**Owner:** Sarang
**Doc type:** Prototype / take-home design exercise

---

## 1. Overview

Mr.Shop users move fluidly between intents within a single chat thread — asking for styling advice, pivoting to a purchase, later booking a stylist consultation — without restating context. This project prototypes the **conversation layer** that makes that possible: an agent with distinct intent-detection, memory, and tool-execution layers, coordinated by an orchestrator.

The prototype is local-first, GPU-optional, and packaged as a Docker image so it can run on any machine with Docker installed, with or without a supported GPU.

## 2. Goals

- Accurately classify user intent across the four core functionalities: wardrobe upload, styling advice, purchase, booking.
- Retain relevant context across turns (wardrobe items, preferences, budget) without requiring repetition.
- Handle at least one graceful topic-switch end-to-end (styling advice → purchase).
- Stay lightweight: fast on CPU, no fine-tuning, no heavy always-on GPU dependency.
- Be runnable by anyone via Docker, regardless of local environment — with a documented, honest degradation path when no GPU/LLM is available.

## 3. Non-goals

- Production-grade purchase/booking flows (all downstream tool actions are mocked).
- Fine-tuned or domain-specific fashion model — general-purpose small LLM used for slot extraction only, not for classification quality.
- Persistent multi-session storage (DB-backed memory) — in-memory session state only, per run.
- A polished UI — terminal REPL for this phase; UI layer explicitly deferred and decoupled.

## 4. Users

Internal reviewers / hiring evaluators assessing the design and a working demo — not end Mr.Shop customers. The "user" simulated in the demo is a Mr.Shop shopper moving between styling, purchase, and booking requests.

## 5. Core functionalities (intents)

| Intent | Description | Example trigger |
|---|---|---|
| `wardrobe_upload` | User describes/adds an item they own | "I just got a navy blazer" |
| `styling_advice` | User wants outfit/styling suggestions | "What goes with dark blue jeans?" |
| `purchase` | User wants to buy or price-check an item | "Can I buy that jacket?" |
| `booking` | User wants to book a stylist consultation | "Book me a stylist call Friday" |
| `unclear` / `chit_chat` | Fallback — no confident match | anything not fitting above |

## 6. System architecture

Three layers plus a tool layer, coordinated by an orchestrator ("agent brain"):

```
Conversation Layer  →  Orchestration Layer  →  Memory Layer
   (terminal REPL)        (agent brain)         (session state)
                               │
                               ▼
                          Tool Layer
              (wardrobe_upload, styling_advice,
                   purchase, booking)
```

- **Conversation layer** — terminal REPL. Pure I/O: reads user input, prints agent reply, no logic.
- **Orchestration layer** — runs intent detection, decides routing (direct tool call, multi-tool chain, or clarifying question), invokes tools, updates memory, owns per-turn execution state (`turn_trace`).
- **Memory layer (ambient)** — session-scoped dict: wardrobe items, preferences, budget, current topic, topic history, last-mentioned item. Read before every classification step, written after every turn.
- **Tool layer** — one pure function per intent, mocked outputs, independent of orchestration logic. Designed so it maps directly onto real function-calling if the orchestrator is later swapped for an LLM-native agent.

## 7. Intent classification — three-tier hybrid

| Tier | Method | When it resolves | Cost |
|---|---|---|---|
| 1 | Keyword/regex rules | Exact, unambiguous keyword hit | Instant, free |
| 2 | Embedding similarity (`all-MiniLM-L6-v2`) | Semantic match above threshold, no keyword hit | CPU, <100ms |
| 3 | Local LLM (optional) | Ambiguous cases; always used for slot extraction & reference resolution | Slower, only tier requiring the LLM |

Tier 3 is invoked for slot extraction/reference resolution ("that jacket") even when Tiers 1–2 already resolved the intent, since fashion conversations rely heavily on implicit references. This is called out as a known cost/latency trade-off (see §11).

## 8. Ambient memory layer — schema

```python
session_state = {
    "wardrobe_items": [...],
    "preferences": {"style": ..., "colors": [...]},
    "budget": None,
    "current_topic": "styling_advice",
    "topic_history": [...],
    "last_mentioned_item": None,
    "pending_action": None,
}
```

Rules:
- Never wiped on topic switch — old topic state is parked, not deleted, so the user can pivot back without re-explaining.
- Shared read/write access between orchestrator and tools (e.g. `purchase` tool can append to a `cart` field).

## 9. Execution/trace state (orchestrator-owned, per turn)

Separate from domain memory — ephemeral bookkeeping for observability and demo legibility:

```python
turn_trace = {
    "turn_id": ...,
    "stage": "CLASSIFYING",  # RECEIVED → CLASSIFYING → ROUTING → TOOL_CALL → MEMORY_UPDATE → RESPONDING → DONE
    "intent_source": None,   # "rule" | "embedding" | "llm" | "clarify"
    "confidence": None,
    "tools_invoked": [],
    "topic_switch": False,
    "latency_ms": {},
}
```

Printed to terminal per turn so the layered pipeline is visible during the demo, not just architecturally true.

## 10. LLM — optional, toggled, degrades gracefully

- **Local only**, no external API calls. Served via Ollama; candidate models: `Phi-3-mini-4k-instruct` or `Llama-3.2-3B-Instruct`, Q4 GGUF quantization.
- **Toggle:** `LLM_ENABLED` env var (`true` / `false` / unset-autodetect via ping to Ollama endpoint at startup).
- **GPU:** used automatically if available and supported (via `nvidia-container-toolkit` passthrough); not a hard requirement.
- **Degraded mode (`LLM_ENABLED=false` or no GPU):**
  - Classification: Tiers 1–2 only. If ambiguous, orchestrator asks a clarifying question instead of guessing.
  - Reference resolution: heuristic fallback — assume `memory["last_mentioned_item"]` when no explicit item is named, and state that assumption explicitly in the reply rather than resolving silently.
- Only the embedding model (Tier 2) is a hard requirement to run the agent at all.

## 11. Async design

- **Orchestrator:** async internally. Tiers 1–2 are CPU-bound and fast but wrapped in async functions for consistency; Tier 3 (LLM call) is a real `await`. Multi-tool turns can use `asyncio.gather` for concurrent tool calls.
- **Conversation layer (REPL):** inherently blocking on user input (expected for chat), but `asyncio.run()` per turn around the orchestrator call rather than the whole process blocking.

## 12. Packaging — Docker

- **Two containers via `docker-compose`:**
  1. `app` — orchestrator, memory, tools, embedding model, REPL. Custom-built image, CPU-only requirements.
  2. `ollama` — official Ollama image, only started if the LLM profile is enabled; hosts the local LLM over `localhost:11434`.
- GPU passthrough is a host prerequisite (`nvidia-container-toolkit` + compose `deploy.resources.reservations.devices` block), not baked into the image — GPU drivers are host-specific and can't be portably bundled.
- Running without a supported GPU: `docker compose up` (app only, LLM profile skipped) — agent still fully functional in degraded mode per §10.

## 13. Deliverables

- Working local demo (terminal), Dockerized, showing 3–4 example conversations, including one full topic-switch (styling advice → purchase) with memory carry-over visible.
- Short design-decisions & trade-offs writeup covering: hybrid classification vs. fine-tuning, local-only LLM vs. API, LLM-as-toggle degradation, two-container Docker split, async boundaries.

## 14. Trade-offs summary (for reviewers)

| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| Classification | Hybrid rules → embeddings → LLM | Fine-tuned fashion model | No training data; classification is a simple decision boundary, doesn't need fine-tuning; fine-tuning would improve advice generation, not intent accuracy — not what's being graded |
| LLM hosting | Local via Ollama | Hosted API | User requirement: fully local, portable, no external dependency |
| LLM necessity | Optional, toggled | Required | Keeps the agent runnable on any machine; only embeddings are a hard requirement |
| Packaging | Two Docker containers (compose) | Single bundled image | Ollama has its own large, independently-updated runtime; bundling would bloat and complicate the app image |
| Interface | Terminal REPL | Streamlit UI | Faster to build and verify core logic first; UI is decoupled and can be layered on later without touching orchestrator/memory/tools |

## 15. Scaling considerations

- New intent = new keyword set + one taxonomy description line + one new tool function. No retraining.
- Rule-layer keyword collisions at scale → replace with pure embedding-based Tier 1/2 merge.
- Memory schema can be namespaced per functionality (`memory["booking"] = {...}`) as functionalities grow.
- Orchestrator's rule-based routing can later be replaced by native LLM function-calling against the same tool layer — tool contracts don't need to change.
- Session state can move from in-process dict to Redis/DB for true multi-session persistence in production.

## 16. Open questions

- Final pick between Phi-3-mini vs Llama-3.2-3B — to be decided empirically (latency/reliability on target hardware) during build.
- Exact embedding similarity threshold for Tier 2 confidence — to be tuned against sample utterances during build.
