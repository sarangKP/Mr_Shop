"""
Tests for mrshop/storage/redis_store.py.

Uses fakeredis so no real Redis server is needed.  fakeredis.FakeRedis
behaves identically to redis.Redis for the operations we use (get, set, ping, ttl).
"""

import json
from unittest.mock import patch, MagicMock

import fakeredis
import pytest

from mrshop.memory.session import new_session
from mrshop.storage.redis_store import load_session, save_session, _session_key


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_client():
    """An in-memory FakeRedis client that resets between tests."""
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def populated_state():
    """A session dict with some non-default values."""
    state = new_session()
    state["wardrobe_items"] = ["navy blazer", "white tee"]
    state["gender"] = "male"
    state["preferences"]["style"] = "smart casual"
    state["preferences"]["colors"] = ["navy", "white"]
    state["last_mentioned_item"] = "navy blazer"
    state["topic_history"] = ["wardrobe_upload", "styling_advice"]
    state["current_topic"] = "purchase"
    return state


# ---------------------------------------------------------------------------
# load_session
# ---------------------------------------------------------------------------

def test_load_session_returns_new_session_when_key_absent(fake_client):
    state = load_session(fake_client, "user123")
    assert state == new_session()


def test_load_session_returns_stored_state(fake_client, populated_state):
    fake_client.set(_session_key("user1"), json.dumps(populated_state))
    loaded = load_session(fake_client, "user1")
    assert loaded == populated_state


def test_load_session_preserves_wardrobe_items(fake_client, populated_state):
    fake_client.set(_session_key("u"), json.dumps(populated_state))
    loaded = load_session(fake_client, "u")
    assert loaded["wardrobe_items"] == ["navy blazer", "white tee"]


def test_load_session_preserves_gender(fake_client, populated_state):
    fake_client.set(_session_key("u"), json.dumps(populated_state))
    loaded = load_session(fake_client, "u")
    assert loaded["gender"] == "male"


def test_load_session_preserves_preferences(fake_client, populated_state):
    fake_client.set(_session_key("u"), json.dumps(populated_state))
    loaded = load_session(fake_client, "u")
    assert loaded["preferences"]["style"] == "smart casual"
    assert set(loaded["preferences"]["colors"]) == {"navy", "white"}


def test_load_session_preserves_topic_history(fake_client, populated_state):
    fake_client.set(_session_key("u"), json.dumps(populated_state))
    loaded = load_session(fake_client, "u")
    assert loaded["topic_history"] == ["wardrobe_upload", "styling_advice"]


# ---------------------------------------------------------------------------
# save_session
# ---------------------------------------------------------------------------

def test_save_then_load_round_trip(fake_client, populated_state):
    save_session(fake_client, "user1", populated_state, ttl=3600)
    loaded = load_session(fake_client, "user1")
    assert loaded == populated_state


def test_save_sets_ttl(fake_client, populated_state):
    save_session(fake_client, "user1", populated_state, ttl=3600)
    ttl = fake_client.ttl(_session_key("user1"))
    assert 0 < ttl <= 3600


def test_save_overwrites_previous_session(fake_client, populated_state):
    save_session(fake_client, "user1", populated_state, ttl=3600)
    populated_state["wardrobe_items"].append("leather jacket")
    save_session(fake_client, "user1", populated_state, ttl=3600)
    loaded = load_session(fake_client, "user1")
    assert "leather jacket" in loaded["wardrobe_items"]


def test_different_users_have_isolated_sessions(fake_client):
    state_a = new_session()
    state_a["wardrobe_items"] = ["red dress"]
    state_b = new_session()
    state_b["wardrobe_items"] = ["blue suit"]

    save_session(fake_client, "alice", state_a, ttl=3600)
    save_session(fake_client, "bob", state_b, ttl=3600)

    assert load_session(fake_client, "alice")["wardrobe_items"] == ["red dress"]
    assert load_session(fake_client, "bob")["wardrobe_items"] == ["blue suit"]


# ---------------------------------------------------------------------------
# get_client — graceful degradation
# ---------------------------------------------------------------------------

def test_get_client_returns_none_when_redis_unreachable():
    from mrshop.storage.redis_store import get_client
    import redis
    with patch("redis.from_url") as mock_from_url:
        mock_client = MagicMock()
        mock_client.ping.side_effect = redis.ConnectionError("refused")
        mock_from_url.return_value = mock_client
        result = get_client()
    assert result is None
