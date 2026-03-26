"""
main.py — FastAPI entrypoint for the Agentic SQL Data Analyst.

Endpoints:
  POST /chat          → send a message, get back text + optional chart
  POST /reset         → clear conversation history for a session
  GET  /schema        → return the live DB schema (useful for the UI)
  GET  /health        → liveness check

Run with:
  uvicorn main:app --reload
"""

import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent import run_agent
from tools.schema import get_schema
from db.seed import seed_database


# ---------------------------------------------------------------------------
# Session store  (in-memory; swap for Redis in production)
# ---------------------------------------------------------------------------

# session_id  →  list of message dicts (the conversation history)
_sessions: dict[str, list[dict]] = {}

MAX_SESSIONS = 500          # evict oldest when limit hit
MAX_HISTORY_TURNS = 40      # per session — keeps context window manageable


def _get_or_create_session(session_id: str) -> list[dict]:
    if session_id not in _sessions:
        if len(_sessions) >= MAX_SESSIONS:
            # Evict the oldest session
            oldest = next(iter(_sessions))
            del _sessions[oldest]
        _sessions[session_id] = []
    return _sessions[session_id]


def _trim_history(history: list[dict]) -> None:
    """Keep the last MAX_HISTORY_TURNS *pairs* (user + assistant)."""
    max_messages = MAX_HISTORY_TURNS * 2
    if len(history) > max_messages:
        del history[: len(history) - max_messages]


# ---------------------------------------------------------------------------
# Lifespan: seed DB on startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_database()          # creates db/sales.db if it doesn't exist
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Agentic SQL Data Analyst",
    description="Natural language → SQL → visual report, powered by Claude.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the frontend from ./frontend/
app.mount("/static", StaticFiles(directory="frontend"), name="static")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None   # if None, a new session is created


class ChatResponse(BaseModel):
    session_id: str
    text: str
    chart_b64: str | None = None    # base64 PNG; None if no chart was generated
    sql_used: str | None = None     # last SQL query Claude ran
    tool_calls: list[dict] = []     # audit trail for the "show reasoning" panel
    turn: int                       # how many user turns in this session


class ResetRequest(BaseModel):
    session_id: str


class ResetResponse(BaseModel):
    session_id: str
    message: str


class SchemaResponse(BaseModel):
    schema: dict                    # table_name → list of {name, type} dicts


class HealthResponse(BaseModel):
    status: str
    sessions_active: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def serve_index():
    """Serve the chat UI."""
    return FileResponse("frontend/index.html")


@app.get("/health", response_model=HealthResponse, tags=["ops"])
async def health():
    return HealthResponse(status="ok", sessions_active=len(_sessions))


@app.get("/schema", response_model=SchemaResponse, tags=["data"])
async def schema():
    """Return the live database schema — handy for the UI's schema panel."""
    try:
        result = get_schema()
        return SchemaResponse(schema=result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/chat", response_model=ChatResponse, tags=["agent"])
async def chat(request: ChatRequest):
    """
    Send a natural-language question.
    Returns the agent's text answer, an optional chart (base64 PNG),
    the SQL that was executed, and a tool-call audit log.
    """
    if not request.message.strip():
        raise HTTPException(status_code=422, detail="Message cannot be empty.")

    # Resolve or create session
    session_id = request.session_id or str(uuid.uuid4())
    history = _get_or_create_session(session_id)

    try:
        agent_response = run_agent(
            user_message=request.message,
            conversation_history=history,   # mutated in-place by the agent
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}")

    # Trim history to stay within context window budget
    _trim_history(history)

    # Count user turns (every other message starting from 0 is a user message)
    turn = sum(1 for m in history if m.get("role") == "user")

    return ChatResponse(
        session_id=session_id,
        text=agent_response.text,
        chart_b64=agent_response.chart_b64,
        sql_used=agent_response.sql_used,
        tool_calls=agent_response.tool_calls,
        turn=turn,
    )


@app.post("/reset", response_model=ResetResponse, tags=["agent"])
async def reset(request: ResetRequest):
    """Clear conversation history for a session."""
    if request.session_id in _sessions:
        del _sessions[request.session_id]
    return ResetResponse(
        session_id=request.session_id,
        message="Session cleared. Starting fresh.",
    )


# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
