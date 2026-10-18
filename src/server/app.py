"""
FastAPI server with SSE streaming.

The model owns the loop — two SSE endpoints make it demonstrable:

  POST /agent/sessions/start_stream         — kick off a session; the agent
                                               diagnoses, plans, and teaches,
                                               streaming each decision live.
  POST /agent/sessions/{id}/respond_stream  — submit a learner response; the
                                               agent decides what happens next.

Each streams the agent's tool calls, summarized reasoning, and generated
lesson as Server-Sent Events, so a UI can render the loop as it unfolds. The
retired fixed-pipeline ("workflow") routes have been removed; the autonomous
agent is the only runtime path. See src/agent/autonomous.py.
"""

from __future__ import annotations

import contextvars
import json
import logging
import queue
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from src.graph.extractor import extract_learning_graph
from src.harness import ExternalCallError, cost
from src.ingestion import (
    MAX_SOURCE_BYTES,
    IngestedSource,
    SourceIngestionError,
    fetch_url,
    parse_source_bytes,
)
from src.agent.autonomous import kickoff_message, observation_message, run_agent_turn
from src.llm import thinking_sink
from src.memory.store import MemoryStore
from src.server.guards import (
    PER_SESSION_USD_CAP,
    DemoTokenMiddleware,
    RateLimiter,
    budget_exhausted_response,
    client_ip,
    daily_budget_exhausted,
    rate_limited_response,
)
from src.schemas import (
    LearnerModel,
    LearningGraph,
    SessionTurn,
)

app = FastAPI(title="Adaptive Learning Agent", version="0.1.0")
app.add_middleware(DemoTokenMiddleware)  # gates session endpoints if DEMO_TOKEN set
store = MemoryStore()
rate_limiter = RateLimiter()
log = logging.getLogger("adaptive_learning.server")


@app.exception_handler(ExternalCallError)
def external_call_error_handler(request, exc: ExternalCallError):
    """
    Upstream (Anthropic API) failure after retries — surface it as a structured
    502 instead of an opaque 500. The SSE path handles this inline instead
    (an error event mid-stream), since headers are already sent by then.
    """
    log.error("external call failed: %s", exc)
    return JSONResponse(status_code=502, content=exc.public_payload())


@app.exception_handler(SourceIngestionError)
def source_ingestion_error_handler(request, exc: SourceIngestionError):
    return JSONResponse(
        status_code=422,
        content={"error": exc.code, "message": str(exc)},
    )

# Visual demo — see docs/visual/index.html. Mount at /visual.
_VISUAL_DIR = Path(__file__).resolve().parents[2] / "docs" / "visual"
if _VISUAL_DIR.exists():
    app.mount("/visual", StaticFiles(directory=str(_VISUAL_DIR), html=True), name="visual")


@app.get("/")
def root():
    """Redirect to the visual demo."""
    if (_VISUAL_DIR / "index.html").exists():
        return FileResponse(str(_VISUAL_DIR / "index.html"))
    return {"status": "ok", "see": "/docs"}

# Sessions are kept in-process for the demo. Production would persist to the
# memory store keyed by session_id alongside graphs and learners.
SESSIONS: dict[str, dict[str, Any]] = {}


class StartSessionRequest(BaseModel):
    user_id: str
    domain_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    # Custom sources are mutually exclusive. Neither means use a preset/cached domain.
    source_text: str | None = None  # raw material to extract a graph from
    source_url: str | None = None
    domain_title: str | None = None
    # Optional: seed the learner state (mastered/struggling/difficulty/history)
    # so a demo can reproduce a specific adaptive decision (e.g. a prereq gap).
    learner: dict | None = None

    @model_validator(mode="after")
    def validate_custom_source(self):
        if self.source_text and self.source_url:
            raise ValueError("Provide source_text or source_url, not both.")
        if self.source_text and len(self.source_text.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError(f"source_text exceeds the {MAX_SOURCE_BYTES // (1024 * 1024)} MB limit.")
        return self


def _seeded_learner(
    req: "StartSessionRequest", *, domain_id: str | None = None
) -> LearnerModel | None:
    """Build a LearnerModel from an explicit seed in the request, if present."""
    if not req.learner:
        return None
    seed = req.learner
    return LearnerModel(
        user_id=req.user_id,
        domain_id=domain_id or req.domain_id,
        mastered_concepts=seed.get("mastered_concepts", []),
        struggling_concepts=seed.get("struggling_concepts", []),
        modality_preference=seed.get("modality_preference", "reading"),
        difficulty_level=seed.get("difficulty_level", 1),
        session_history=[SessionTurn(**t) for t in seed.get("session_history", [])],
    )


class RespondRequest(BaseModel):
    correct: bool
    notes: str = ""


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/graphs")
def list_graphs():
    return {"graphs": store.list_graphs()}


@app.post("/sources/parse")
async def parse_uploaded_source(request: Request, filename: str = "source.txt"):
    """Parse a raw file upload without requiring multipart form dependencies."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_SOURCE_BYTES:
            raise SourceIngestionError(
                f"The source exceeds the {MAX_SOURCE_BYTES // (1024 * 1024)} MB limit.",
                code="source_too_large",
            )
        chunks.append(chunk)
    source = parse_source_bytes(
        b"".join(chunks),
        filename=filename,
        content_type=request.headers.get("content-type"),
    )
    return {
        "source_text": source.text,
        "domain_title": source.title,
        "source_type": source.source_type,
    }


@app.get("/evals")
def get_evals():
    """Serve the live eval-harness results (6 golden cases × 3 judges)."""
    results_path = Path(__file__).resolve().parents[2] / "evals" / "results.json"
    if not results_path.exists():
        raise HTTPException(
            status_code=404,
            detail="No eval results yet. Run: python run_evals.py --json evals/results.json",
        )
    cases = json.loads(results_path.read_text(encoding="utf-8"))
    PASS_THRESHOLD = 0.6
    summary = []
    for c in cases:
        judges = c.get("judge_results", [])
        passed = all(j["score"] >= PASS_THRESHOLD for j in judges) if judges else False
        summary.append({
            "case_id": c["case_id"],
            "passed": passed,
            "judges": judges,
            "workflow": c.get("workflow", {}),
            "artifact_type": c.get("artifact_type"),
        })
    n_pass = sum(1 for s in summary if s["passed"])
    return {
        "pass_threshold": PASS_THRESHOLD,
        "n_pass": n_pass,
        "n_total": len(summary),
        "cases": summary,
    }


def _cost_summary(session_usd: float) -> dict:
    """Per-session spend so far + how much of the cap remains."""
    return {
        "session_usd": round(session_usd, 4),
        "session_cap_usd": PER_SESSION_USD_CAP,
        "cap_reached": session_usd >= PER_SESSION_USD_CAP,
    }


def _sse_event(event_type: str, data: dict) -> str:
    """Format one Server-Sent Event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _thinking_events(phase: str, fn: Callable[[], Any], meter: cost.CostMeter):
    """
    Run an LLM-backed phase in a worker thread, streaming its progress as SSE
    events; the phase's return value comes back via `yield from`.

      - 'thinking' events carry summarized-reasoning deltas as the model
        produces them.
      - 'progress' events carry a running character count while the model
        writes its (JSON) answer — reasoning summaries go quiet during that
        stretch, and without this the UI sits frozen for tens of seconds.

    The session's cost meter is adopted explicitly inside the thread — the
    generator's own context can't be relied on (each next() runs in a fresh
    context copy).
    """
    q: queue.Queue[tuple[str, str] | None] = queue.Queue()
    out: dict[str, Any] = {}
    ctx = contextvars.copy_context()

    def worker():
        try:
            with cost.use_meter(meter), thinking_sink(lambda kind, delta: q.put((kind, delta))):
                out["value"] = fn()
        except BaseException as e:  # re-raised on the generator side
            out["error"] = e
        finally:
            q.put(None)

    threading.Thread(target=lambda: ctx.run(worker), daemon=True).start()
    chars = 0
    last_progress = 0
    while True:
        item = q.get()
        if item is None:
            break
        kind, delta = item
        if kind == "thinking":
            yield _sse_event("thinking", {"phase": phase, "delta": delta})
        else:  # "text" — throttle to one progress event per ~120 chars
            chars += len(delta)
            if chars - last_progress >= 120:
                last_progress = chars
                yield _sse_event("progress", {"phase": phase, "chars": chars})
    if "error" in out:
        raise out["error"]
    return out["value"]


# ---------------------------------------------------------------------------
# Autonomous orchestration mode (/agent/...): same tools, same guards, same
# meter — but the MODEL owns the loop. See src/agent/autonomous.py.
# ---------------------------------------------------------------------------


def _agent_events(state: dict, message: str, meter: cost.CostMeter):
    """Run one autonomous turn in a worker thread, yielding SSE events for the
    agent's tool activity, decisions, and streamed reasoning."""
    q: queue.Queue = queue.Queue()
    out: dict[str, Any] = {}
    ctx = contextvars.copy_context()

    def worker():
        try:
            with cost.use_meter(meter), thinking_sink(
                lambda kind, delta: q.put(("delta", kind, delta))
            ):
                out["value"] = run_agent_turn(
                    state, message, lambda t, p: q.put(("event", t, p))
                )
        except BaseException as e:  # re-raised on the generator side
            out["error"] = e
        finally:
            q.put(None)

    threading.Thread(target=lambda: ctx.run(worker), daemon=True).start()
    chars = 0
    last_progress = 0
    while True:
        item = q.get()
        if item is None:
            break
        if item[0] == "delta":
            _, kind, delta = item
            if kind == "thinking":
                yield _sse_event("thinking", {"phase": "agent", "delta": delta})
            else:
                chars += len(delta)
                if chars - last_progress >= 120:
                    last_progress = chars
                    yield _sse_event("progress", {"phase": "agent", "chars": chars})
        else:
            _, t, p = item
            yield _sse_event(t, p)
    if "error" in out:
        raise out["error"]
    return out.get("value")


@app.post("/agent/sessions/start_stream")
def agent_start_session_stream(req: StartSessionRequest, request: Request):
    """Autonomous-mode session start: the model decides each move."""
    if daily_budget_exhausted():
        return budget_exhausted_response()
    if not rate_limiter.check(client_ip(request)):
        return rate_limited_response()

    def event_stream():
        session_meter = cost.CostMeter()
        try:
            # Graph resolution — mirrors workflow mode.
            domain_path = Path("domains") / f"{req.domain_id}.md"
            yield _sse_event("phase", {"name": "load_graph"})
            graph: LearningGraph | None = None
            custom_source: IngestedSource | None = None
            if req.source_url:
                custom_source = fetch_url(req.source_url)
            elif req.source_text:
                custom_source = IngestedSource(
                    text=req.source_text,
                    title=req.domain_title or req.domain_id.replace("_", " "),
                    source_type="text",
                )

            if custom_source is not None:
                graph = yield from _thinking_events(
                    "load_graph",
                    lambda: extract_learning_graph(
                        custom_source.text,
                        req.domain_title or custom_source.title,
                        store,
                    ),
                    session_meter,
                )
            elif domain_path.exists():
                source = domain_path.read_text(encoding="utf-8")
                graph = yield from _thinking_events(
                    "load_graph",
                    lambda: extract_learning_graph(
                        source,
                        req.domain_title or req.domain_id.replace("_", " "),
                        store,
                    ),
                    session_meter,
                )
            else:
                for entry in store.list_graphs():
                    if entry["domain_id"] == req.domain_id:
                        graph = store.get_graph_by_source_hash(entry["source_hash"])
                        break
            if graph is None:
                yield _sse_event(
                    "error", {"message": f"No graph for domain {req.domain_id!r}."}
                )
                return
            effective_domain_id = graph.domain_id
            yield _sse_event(
                "graph",
                {
                    "domain_id": graph.domain_id,
                    "n_nodes": len(graph.nodes),
                    "nodes": [
                        {
                            "id": n.concept_id,
                            "name": n.name,
                            "difficulty": n.difficulty,
                            "prerequisites": n.prerequisites,
                        }
                        for n in graph.nodes
                    ],
                },
            )

            learner = _seeded_learner(req, domain_id=effective_domain_id)
            if learner is not None:
                store.save_learner(learner)
            else:
                learner = store.get_learner(req.user_id, effective_domain_id)
                if learner is None:
                    learner = LearnerModel(user_id=req.user_id, domain_id=effective_domain_id)
                    store.save_learner(learner)
            yield _sse_event("learner", {"learner": learner.model_dump(mode="json")})

            agent_state: dict[str, Any] = {
                "learner": learner,
                "graph": graph,
                "store": store,
                "messages": [],
                "steps_taught": 0,
            }
            session_id = uuid.uuid4().hex[:12]
            SESSIONS[session_id] = {
                "mode": "agent",
                "user_id": req.user_id,
                "domain_id": effective_domain_id,
                "state": agent_state,
                "cost_usd": 0.0,
            }

            yield from _agent_events(
                agent_state, kickoff_message(learner, graph), session_meter
            )

            SESSIONS[session_id]["cost_usd"] = session_meter.total_usd
            yield _sse_event(
                "session_ready",
                {
                    "session_id": session_id,
                    "mode": "agent",
                    "cost": _cost_summary(session_meter.total_usd),
                },
            )
        except ExternalCallError as e:
            log.error("external call failed: %s", e)
            yield _sse_event("error", e.public_payload())
        except Exception:
            log.exception("session stream failed")
            yield _sse_event("error", {"error": "internal_error",
                                       "message": "Something went wrong on our side. Start a new session."})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/agent/sessions/{session_id}/respond_stream")
def agent_respond_stream(session_id: str, req: RespondRequest):
    """Autonomous-mode learner answer: the model decides what happens next."""
    sess = SESSIONS.get(session_id)
    if sess is None or sess.get("mode") != "agent":
        raise HTTPException(status_code=404, detail="Agent session not found")
    if daily_budget_exhausted():
        return budget_exhausted_response()

    def event_stream():
        meter = cost.CostMeter()
        try:
            if sess.get("cost_usd", 0.0) >= PER_SESSION_USD_CAP:
                yield _sse_event(
                    "turn_done",
                    {
                        "status": "session_budget_reached",
                        "cost": _cost_summary(sess["cost_usd"]),
                    },
                )
                return
            yield from _agent_events(
                sess["state"], observation_message(req.correct, req.notes), meter
            )
            sess["cost_usd"] = sess.get("cost_usd", 0.0) + meter.total_usd
            yield _sse_event(
                "turn_done",
                {"status": "awaiting_learner", "cost": _cost_summary(sess["cost_usd"])},
            )
        except ExternalCallError as e:
            log.error("external call failed: %s", e)
            yield _sse_event("error", e.public_payload())
        except Exception:
            log.exception("session stream failed")
            yield _sse_event("error", {"error": "internal_error",
                                       "message": "Something went wrong on our side. Start a new session."})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
