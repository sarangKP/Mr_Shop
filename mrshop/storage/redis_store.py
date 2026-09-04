"""
Redis session storage — the persistence layer for Mr.Shop sessions.

Provides three functions:
  get_client()          → Redis client or None (graceful degradation if unreachable)
  load_session(...)     → deserialise session dict from Redis, or fresh session if absent
  save_session(...)     → serialise session dict to Redis with TTL

Key format:  mrshop:session:{user_id}
TTL:         REDIS_TTL env var (default 86400 — 24 hours)

Design notes:
  - The orchestrator and memory layer are unaware of Redis — they work with plain dicts.
  - get_client() returns None when Redis is down so the REPL can degrade gracefully
    (in-memory only, session not persisted) without crashing.
  - json.dumps / json.loads is sufficient because session state contains only strings,
    lists, and None — no custom types.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from mrshop.memory.session import new_session

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_DEFAULT_TTL = int(os.getenv("REDIS_TTL", "86400"))


def _session_key(user_id: str) -> str:
    return f"mrshop:session:{user_id}"


def get_client():
    """
    Return a connected Redis client, or None if Redis is unreachable.

    Reads REDIS_URL from the environment (default: redis://localhost:6379).
    A ping is issued immediately to confirm connectivity — if it fails,
    None is returned and the caller runs in-memory only.
    """
    import redis
    try:
        client = redis.from_url(_REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def load_session(client, user_id: str) -> dict:
    """
    Load a session from Redis.

    Returns the deserialised session dict if the key exists, or a fresh
    new_session() dict if the user has no stored session yet.
    """
    raw = client.get(_session_key(user_id))
    if raw is None:
        return new_session()
    return json.loads(raw)


def save_session(client, user_id: str, state: dict, ttl: int = _DEFAULT_TTL) -> None:
    """
    Persist the session dict to Redis with a TTL.

    The key expires automatically after `ttl` seconds of inactivity so
    old sessions are cleaned up without a separate job.
    """
    client.set(_session_key(user_id), json.dumps(state), ex=ttl)
