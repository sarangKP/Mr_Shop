"""
Terminal REPL — the user-facing conversation loop (PRD §6).

Responsibilities:
  - Print a welcome banner and boot the orchestrator.
  - Read user input line by line (blocking on input is expected for chat).
  - Call orchestrator.handle_turn(utterance) and print the reply.
  - Print turn_trace after every turn so the pipeline is visible during the demo.
  - Exit cleanly on "quit" / "exit" / Ctrl-C / EOF.

No business logic here — all decisions happen in the orchestrator.
Step 8 will convert handle_turn to async and add asyncio.run() here.
"""

import asyncio
import os

from mrshop import config
from mrshop.memory import session
from mrshop.orchestrator.orchestrator import Orchestrator
from mrshop.storage import redis_store as storage

_BANNER = """
╔══════════════════════════════════════════════════════╗
║          Mr.Shop — Personal Styling Assistant        ║
║                                                      ║
║  I can help you with:                               ║
║    • Adding items to your wardrobe                  ║
║    • Styling & outfit advice                        ║
║    • Purchasing items                               ║
║    • Booking a stylist consultation                 ║
║                                                      ║
║  Type 'quit' or Ctrl-C to exit.                     ║
╚══════════════════════════════════════════════════════╝
"""


def main() -> None:
    """Entry point — starts the REPL loop."""
    print(_BANNER)
    print("Loading embedding model...", flush=True)

    resolver, reply_fn = asyncio.run(config.bootstrap())

    # Redis session persistence — degrades gracefully if Redis is unreachable.
    user_id = os.getenv("MRSHOP_USER_ID", "local")
    ttl = int(os.getenv("REDIS_TTL", "86400"))
    redis_client = storage.get_client()
    if redis_client:
        state = storage.load_session(redis_client, user_id)
        wardrobe = session.get(state, "wardrobe_items")
        print(f"[storage] Session restored from Redis (user={user_id}, "
              f"wardrobe={len(wardrobe)} item(s))")
    else:
        state = session.new_session()
        print("[storage] Redis unavailable — running in-memory only (session won't persist)")

    # Ask for gender once — skip if already stored in Redis from a previous session.
    if session.get(state, "gender") is None:
        session.set_gender(state, _prompt_gender())
        _persist(redis_client, user_id, state, ttl)

    orch = Orchestrator(resolve_reference=resolver, generate_reply=reply_fn, state=state)

    print("Ready!\n")

    while True:
        try:
            raw = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            _persist(redis_client, user_id, state, ttl)
            break

        if not raw:
            continue

        if raw.lower() in ("quit", "exit", "bye", "q"):
            print("Goodbye!")
            _persist(redis_client, user_id, state, ttl)
            break

        print("\nMr.Shop: ", end="", flush=True)
        reply, trace = asyncio.run(orch.handle_turn(raw, on_token=_stream_token))
        print("\n")
        _print_trace(trace)
        print()
        _persist(redis_client, user_id, state, ttl)


def _persist(client, user_id: str, state: dict, ttl: int) -> None:
    """Save session to Redis if a client is available."""
    if client:
        storage.save_session(client, user_id, state, ttl)


def _prompt_gender() -> str:
    """Ask the user for their gender once at session start. Accepts m/f or full words."""
    print("\nOne quick question before we start:")
    while True:
        try:
            ans = input("Are you Male or Female? (m/f): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "male"  # safe default for non-interactive environments
        if ans in ("m", "male"):
            return "male"
        if ans in ("f", "female"):
            return "female"
        print("Please enter 'm' for male or 'f' for female.")


def _stream_token(chunk: str) -> None:
    """Print a single token/chunk to stdout without a newline, flushing immediately."""
    import time
    print(chunk, end="", flush=True)
    time.sleep(0.05)  # ~20ms per token — adjust for faster/slower feel


def _print_trace(trace: dict) -> None:
    """Print turn_trace in a compact, readable format per PRD §9."""
    lms = trace["latency_ms"]
    latency_parts = "  ".join(f"{k}={v}ms" for k, v in lms.items())

    print("  ┌─ trace ───────────────────────────────────────────")
    print(f"  │ turn #{trace['turn_id']:02d}  "
          f"source={trace['intent_source']}  "
          f"confidence={trace['confidence']}")
    print(f"  │ tools={trace['tools_invoked']}  "
          f"topic_switch={trace['topic_switch']}  "
          f"resolver={trace.get('resolver_source')}")
    print(f"  │ {latency_parts}")
    print("  └────────────────────────────────────────────────────")
