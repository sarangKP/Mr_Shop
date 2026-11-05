"""Tiny web wrapper around the Mr.Shop orchestrator (chat UI demo).

Runs the real orchestrator, tools, memory and Redis storage.
If sentence-transformers is not installed, Tier 2 is switched off and only
Tier 1 rules classify (anything else becomes "unclear").
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

import mrshop.tools.wardrobe, mrshop.tools.styling, mrshop.tools.purchase, mrshop.tools.booking  # noqa: F401,E401
from mrshop.classifier import tier2
from mrshop.classifier.resolver import heuristic_resolve
from mrshop.generator.reply import template_reply
from mrshop.memory import session
from mrshop.orchestrator.orchestrator import Orchestrator
from mrshop.storage import redis_store as storage

try:
    tier2.load_model()
    TIER2 = True
except Exception:
    tier2.classify = lambda utterance, threshold=0.33: (None, 0.0)
    TIER2 = False

TTL = int(os.getenv("REDIS_TTL", "86400"))
redis_client = storage.get_client()
app = FastAPI()
_sessions: dict[str, dict] = {}


class Msg(BaseModel):
    user_id: str = "web"
    text: str


def _state(user_id: str) -> dict:
    if user_id not in _sessions:
        st = storage.load_session(redis_client, user_id) if redis_client else session.new_session()
        if session.get(st, "gender") is None:
            session.set_gender(st, "male")
        _sessions[user_id] = st
    return _sessions[user_id]


def _summary(st: dict) -> dict:
    return {
        "wardrobe": session.get(st, "wardrobe_items"),
        "budget": session.get(st, "budget"),
        "preferences": session.get(st, "preferences"),
        "topics": session.get(st, "topic_history"),
        "redis": bool(redis_client),
        "tier2": TIER2,
    }


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/api/state")
def state(user_id: str = "web"):
    return _summary(_state(user_id))


@app.post("/api/chat")
async def chat(m: Msg):
    st = _state(m.user_id)
    orch = Orchestrator(resolve_reference=heuristic_resolve, generate_reply=template_reply, state=st)
    reply, trace = await orch.handle_turn(m.text)
    if redis_client:
        storage.save_session(redis_client, m.user_id, st, TTL)
    return {"reply": reply, "trace": trace, "state": _summary(st)}


@app.post("/api/reset")
def reset(user_id: str = "web"):
    _sessions.pop(user_id, None)
    if redis_client:
        redis_client.delete(f"mrshop:session:{user_id}")
    return _summary(_state(user_id))
