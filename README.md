# Mr.Shop — Personal Styling Assistant

Mr.Shop is a terminal-based AI conversation agent for a fashion app. You talk to it naturally — add clothes to your wardrobe, ask for outfit advice, buy items, or book a stylist — all in one flowing conversation without repeating yourself.

It remembers everything: your wardrobe, your gender, your budget, your style preferences, and your conversation history. Sessions persist across restarts via Redis, so picking up where you left off is automatic.

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | ≥ 3.13 | |
| [uv](https://docs.astral.sh/uv/) | latest | package manager |
| Redis | ≥ 7.0 | for session persistence (`sudo apt install redis-server`) |
| [Ollama](https://ollama.com) | latest | optional — for LLM responses |

**Ollama model** (if using LLM mode):
```bash
ollama pull llama3.2:3b
```

---

## Installation

```bash
git clone <repo-url>
cd dr_tracker
uv sync
```

That's it. All Python dependencies (sentence-transformers, httpx, redis, etc.) install automatically.

---

## Running

```bash
uv run mrshop
```

On first run you'll be asked for your gender (stored in Redis — not asked again). After that, just start talking.

```
╔══════════════════════════════════════════════════════╗
║          Mr.Shop — Personal Styling Assistant        ║
╚══════════════════════════════════════════════════════╝

[storage] Session restored from Redis (user=local, wardrobe=2 item(s))
Ready!

You: What goes with my navy blazer?
Mr.Shop: Your navy blazer pairs really well with slim chinos and loafers for
a smart casual look, or dark jeans and white sneakers if you want something
more relaxed...
```

Type `quit` or press `Ctrl-C` to exit. Your session saves automatically.

### Mode flags

```bash
uv run mrshop                       # auto — uses LLM if Ollama is reachable
LLM_ENABLED=false uv run mrshop    # heuristic/template mode, no Ollama needed
LLM_ENABLED=true uv run mrshop     # force LLM mode
MRSHOP_USER_ID=alice uv run mrshop # separate session for a different user
```

### What you can say

| What you want | Example |
|---------------|---------|
| Add an item to your wardrobe | "I just got a navy blazer" |
| See your wardrobe | "What do I have?" / "Show my wardrobe" |
| Get styling advice | "What goes with dark jeans?" / "Style it for a date night" |
| Buy something | "I want to buy that jacket" / "How much does it cost?" |
| Book a stylist | "Book me a stylist call Friday" |
| Set your budget | "My budget is $200" |
| Express preferences | "I love minimalist style" / "I prefer navy and black" |

References like "it", "that", and "the jacket" are resolved from context — no need to repeat item names.

### Live session monitor

To watch Redis saves happen in real time, open a second terminal:

```bash
redis-cli monitor
```

---

## Architecture

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {
  'primaryColor': '#2d1b69',
  'primaryTextColor': '#e8d5ff',
  'primaryBorderColor': '#7c3aed',
  'lineColor': '#9f67ff',
  'secondaryColor': '#1e1040',
  'tertiaryColor': '#16082e',
  'background': '#0f0520',
  'mainBkg': '#2d1b69',
  'nodeBorder': '#7c3aed',
  'clusterBkg': '#1a0d3d',
  'clusterBorder': '#6d28d9',
  'titleColor': '#c4b5fd',
  'edgeLabelBackground': '#1a0d3d',
  'attributeBackgroundColorOdd': '#2d1b69',
  'attributeBackgroundColorEven': '#1e1040'
}}}%%
flowchart TD
    A([User utterance]) --> B

    subgraph Classification ["Intent Classification"]
        B[Tier 1 — keyword/regex\ninstant, confidence 1.0]
        B -->|hit| D
        B -->|miss| C
        C[Tier 2 — embedding similarity\nall-MiniLM-L6-v2, ~90ms CPU]
        C -->|confident| D
        C -->|unclear| D
    end

    D[intent + confidence] --> E

    subgraph SideChannel ["Side-Channel Extraction (every turn)"]
        SC1[gender regex]
        SC2[budget regex]
        SC3[style + colour regex]
    end

    D --> SideChannel

    subgraph Resolution ["Reference Resolution"]
        E{intent?}
        E -->|unclear| E0[skip — no item needed]
        E -->|wardrobe tools| E1[heuristic_resolve\nclothing noun extraction]
        E -->|other + LLM on| F[llm_resolve\nOllama HTTP call]
        E -->|other + LLM off| G[heuristic_resolve\nregex + last_mentioned_item]
        F -->|failure| G
    end

    E0 & E1 & F & G --> H[resolved item]
    H --> I

    subgraph Tools ["Tool Dispatch — registry-driven"]
        I{intent}
        I -->|wardrobe_upload| J1[wardrobe_upload]
        I -->|wardrobe_list| J2[wardrobe_list]
        I -->|styling_advice| J3[styling_advice]
        I -->|purchase| J4[purchase]
        I -->|booking| J5[booking]
        I -->|unclear| J6[no tool — LLM handles]
    end

    J1 & J2 & J3 & J4 & J5 & J6 --> K

    subgraph Memory ["Session Memory (Redis-backed)"]
        K[("wardrobe_items · cart — transient\ngender · budget\npreferences: style + colors\nlast_mentioned_item · last_suggested_items\ntopic_history")]
    end

    K --> L

    subgraph Response ["Response Generation"]
        L{LLM enabled?}
        L -->|yes| M[llm_reply\nOllama — streamed token by token\nfull session context injected]
        L -->|no| N[template_reply\ndeterministic fallback]
        M -->|failure| N
    end

    N --> O([Natural reply → terminal])
    M --> O

    style A fill:#4c1d95,stroke:#7c3aed,color:#e8d5ff
    style O fill:#4c1d95,stroke:#7c3aed,color:#e8d5ff
    style D fill:#3b0764,stroke:#9333ea,color:#e8d5ff
    style H fill:#3b0764,stroke:#9333ea,color:#e8d5ff
    style E fill:#5b21b6,stroke:#a855f7,color:#e8d5ff
    style I fill:#5b21b6,stroke:#a855f7,color:#e8d5ff
    style L fill:#5b21b6,stroke:#a855f7,color:#e8d5ff
    style B fill:#2e1065,stroke:#7c3aed,color:#ddd6fe
    style C fill:#2e1065,stroke:#7c3aed,color:#ddd6fe
    style SC1 fill:#1e0a4a,stroke:#6d28d9,color:#c4b5fd
    style SC2 fill:#1e0a4a,stroke:#6d28d9,color:#c4b5fd
    style SC3 fill:#1e0a4a,stroke:#6d28d9,color:#c4b5fd
    style E0 fill:#1e0a4a,stroke:#6d28d9,color:#c4b5fd
    style E1 fill:#1e0a4a,stroke:#6d28d9,color:#c4b5fd
    style F fill:#2e1065,stroke:#9333ea,color:#ddd6fe
    style G fill:#1e0a4a,stroke:#6d28d9,color:#c4b5fd
    style J1 fill:#1e0a4a,stroke:#6d28d9,color:#c4b5fd
    style J2 fill:#1e0a4a,stroke:#6d28d9,color:#c4b5fd
    style J3 fill:#1e0a4a,stroke:#6d28d9,color:#c4b5fd
    style J4 fill:#1e0a4a,stroke:#6d28d9,color:#c4b5fd
    style J5 fill:#1e0a4a,stroke:#6d28d9,color:#c4b5fd
    style J6 fill:#1e0a4a,stroke:#6d28d9,color:#c4b5fd
    style K fill:#2e1065,stroke:#9333ea,color:#ddd6fe
    style M fill:#2e1065,stroke:#9333ea,color:#ddd6fe
    style N fill:#1e0a4a,stroke:#6d28d9,color:#c4b5fd
```

---

## Running Tests

```bash
uv run pytest -q          # 224 tests, all passing
```

Individual suites:

```bash
uv run pytest tests/test_memory.py        # session state schema + helpers
uv run pytest tests/test_tools.py         # wardrobe/styling/purchase/booking tools
uv run pytest tests/test_classifier.py    # Tier 1 + Tier 2 classification
uv run pytest tests/test_orchestrator.py  # routing, topic switch, traces
uv run pytest tests/test_e2e.py           # full pipeline conversations
uv run pytest tests/test_tier3.py         # LLM resolver + reply generation + bootstrap
uv run pytest tests/test_storage.py       # Redis load/save/TTL/multi-user (fakeredis)
```

No real Redis or Ollama server needed for tests — both are mocked.

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_ENABLED` | `auto` | `true` / `false` / `auto` (pings Ollama at startup) |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server address |
| `OLLAMA_MODEL` | `llama3.2:3b` | Model to use for responses |
| `TIER2_THRESHOLD` | `0.33` | Embedding confidence cutoff (0–1) |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection string |
| `REDIS_TTL` | `86400` | Session expiry in seconds (24 hours) |
| `MRSHOP_USER_ID` | `local` | Per-user session key — change for multi-user setups |

---

## Project Scope

### 1. Intent Classification

A three-tier pipeline classifies every user utterance into one of five intents:

| Intent | Example utterances |
|--------|-------------------|
| `wardrobe_upload` | "I just got a navy blazer", "I also have baggy jeans" |
| `wardrobe_list` | "What's in my wardrobe?", "Show me all my clothes" |
| `styling_advice` | "What goes with dark jeans?", "Style it for a date night" |
| `purchase` | "I want to buy that jacket", "How much does it cost?" |
| `booking` | "Book me a stylist call Friday", "Schedule a styling session" |

**Tier 1 — keyword/regex** (`mrshop/classifier/tier1.py`): Instant, deterministic rules.
Handles clear-cut phrases like "I just got", "book me a stylist", "I want to buy".
Returns confidence 1.0 on a hit, passes to Tier 2 on a miss. Rules are read lazily
from the tool registry — adding a new tool's patterns requires no changes here.

**Tier 2 — embedding similarity** (`mrshop/classifier/tier2.py`): `all-MiniLM-L6-v2`
encodes the utterance and compares it against a taxonomy of representative sentences
per intent. Taxonomy sentences are also read from the tool registry at startup — no
changes to the classifier when adding a new intent.

**Fallback — LLM response layer**: Utterances that don't clear either tier's confidence
threshold are treated as `unclear`. Rather than a canned error message, the LLM
handles these naturally — greetings, off-topic messages, and vague requests all get
a coherent conversational response.

---

### 2. Context / Memory Layer (the Ambient Layer)

Session state (`mrshop/memory/session.py`) persists across every topic switch and
across sessions via Redis. The user never needs to repeat themselves.

| Field | What it captures | How it's populated |
|-------|-----------------|-------------------|
| `wardrobe_items` | All clothing items the user owns — populated by wardrobe upload **and purchase** | `wardrobe_upload` + `purchase` tools |
| `cart` | Transient purchase basket — cleared automatically after each fulfilled order | `purchase` tool |
| `gender` | Self-identification — asked once at startup | startup prompt + regex side-channel |
| `budget` | Stated budget ("$200", "budget of 150") | regex side-channel |
| `preferences.style` | Style preference ("I love minimalist") | regex side-channel |
| `preferences.colors` | Favourite colours — union across turns | regex side-channel |
| `last_mentioned_item` | Most recently referenced item — fallback when no suggestion context exists | resolver + tools |
| `last_suggested_items` | Items from the most recent styling suggestion — resolved first when user says "buy that" / "those items" | `styling_advice` tool |
| `topic_history` | Ordered list of past intents | orchestrator |
| `current_topic` | Active intent | orchestrator |

**Side-channel extraction**: On every turn, three independent regex passes run
against the raw utterance before any tool is called. Gender, budget, and
style/colour preferences are extracted and written to session memory regardless
of the classified intent — a user mentioning "I prefer earth tones" mid-purchase
gets that preference stored and injected into every subsequent LLM reply.

**Reference resolution** (`mrshop/classifier/resolver.py`): When a user says "style it",
"buy that", or "purchase those items", the resolver maps the pronoun to the correct item:
- `heuristic_resolve` — clothing-noun regex → pronoun check against `last_suggested_items` → `last_mentioned_item` fallback
- `llm_resolve` — Ollama prompt (with wardrobe + `last_suggested_items` context) for specific item references; skips Ollama entirely for pronoun-only utterances ("buy that", "add it") where the heuristic context is more reliable than a small LLM

Resolution is skipped entirely for `unclear` intent — there is no item to resolve,
and running the resolver on greetings caused junk words to pollute `last_mentioned_item`.

---

### 3. Topic-Switch Scenario (end-to-end)

```
You: I just got a navy blazer
Mr.Shop: Great, I've added your navy blazer to your wardrobe!
  trace → intent=wardrobe_upload (rule, 1.0) | topic=wardrobe_upload

You: What goes with dark blue jeans?
Mr.Shop: Your navy blazer pairs beautifully with dark blue jeans...
  trace → intent=styling_advice (rule, 1.0) | topic_switch=True

You: I want to buy that jacket
Mr.Shop: Purchase started for 'navy blazer' at $189.99. Added to your wardrobe.
  trace → intent=purchase (rule, 1.0) | topic_switch=True | resolver=llm
                                        ↑ "that jacket" resolved to "navy blazer"
                                          via LLM using last_mentioned_item context
                                        ↑ cart cleared after fulfilment; item now in wardrobe

You: Book me a stylist call Friday
Mr.Shop: Booked! Stylist Alex will see you Friday at 2pm. Confirmation: MRSHOP-4821.
  trace → intent=booking (rule, 1.0) | topic_switch=True
```

What the memory layer preserved across all four turns:
- `wardrobe_items = ["navy blazer"]` — added at upload, confirmed again after purchase
- `last_mentioned_item = "navy blazer"` — resolved "that jacket" correctly in turn 3
- `cart = []` — cleared after the purchase was fulfilled
- `topic_history = ["wardrobe_upload", "styling_advice", "purchase"]` — full audit trail

---

### 4. Scaling to Additional Functionalities

The architecture uses a plugin registry so that adding a new capability requires
changes in exactly **one place** — no orchestrator rewrites, no classifier edits,
no prompt engineering overhauls.

**Adding a new intent** — create one file and call `register()`:

```python
# mrshop/tools/size_check.py
from mrshop.tools.registry import ToolDefinition, register

def size_check(item: str, state: dict) -> dict:
    return {"item": item, "size": "M", "available": True}

register(ToolDefinition(
    intent="size_check",
    tier1_priority=35,
    tier1_patterns=[r"\bwhat size (is|should)\b", r"\bdo you have .{0,20} in\b"],
    tier2_examples=["What size is this item?", "Do you have this in medium?"],
    llm_instruction="Confirm the size and availability. 1–2 sentences.",
    run=lambda utterance, resolved_item, state: size_check(resolved_item or utterance, state),
))
```

Tier 1 rules, Tier 2 taxonomy, orchestrator dispatch, and LLM prompt instructions
all update automatically — zero changes to any other file.

**Swappable LLM provider**: Both the resolver and reply generator are `Callable` type
aliases injected at startup via `config.bootstrap()`. Swapping from Ollama to OpenAI,
Gemini, or a fine-tuned model means implementing one new async function — the
orchestrator, tools, and memory layer are completely unaffected.

**Scaling memory**: Adding a new session field means adding it to `new_session()` (the
schema guard raises `KeyError` immediately on unknown keys), adding a typed helper, and
including it in `_build_reply_prompt()`.

**Multi-user / persistence**: Session state is persisted to Redis after every turn,
namespaced by `MRSHOP_USER_ID`. The same Redis instance serves multiple users with no
code changes. If Redis is unreachable the agent degrades gracefully to in-memory only.

---

## Project Layout

```
mrshop/
  config.py             # startup wiring — selects resolver + reply generator
  classifier/
    tier1.py            # keyword/regex rules (lazy-loaded from registry)
    tier2.py            # embedding similarity + taxonomy (lazy-loaded from registry)
    resolver.py         # ResolverFn interface, heuristic_resolve, llm_resolve
  generator/
    reply.py            # ReplyFn interface, template_reply, llm_reply (streaming)
  memory/
    session.py          # session_state schema + typed read/write helpers
  storage/
    redis_store.py      # get_client / load_session / save_session (TTL + multi-user)
  tools/
    registry.py         # ToolDefinition dataclass — the plugin registration point
    wardrobe.py         # wardrobe_upload + wardrobe_list + registrations
    styling.py          # styling_advice tool + registration
    purchase.py         # purchase tool + registration
    booking.py          # booking tool + registration
  orchestrator/
    orchestrator.py     # routes turns, side-channel extraction, owns turn_trace
  conversation/
    repl.py             # terminal REPL — streaming output, gender prompt, pure I/O
tests/                  # 224 tests across 7 files (fakeredis — no real services needed)
DESIGN.md               # example conversations + design decisions
```
