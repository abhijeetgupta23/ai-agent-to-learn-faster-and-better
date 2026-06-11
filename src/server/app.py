"""
FastAPI server with SSE streaming.

Two endpoints make the system demonstrable:

  POST /sessions/start         — kick off a session; returns session_id + first
                                  artifact (no SSE; one round-trip).
  POST /sessions/{id}/respond  — submit a learner response; returns next event
                                  stream until the next observation point or
                                  end of workflow.

The simpler shape (vs full SSE through a long-running coroutine) was chosen
because it's easier to demo with curl and integrates more cleanly with the
eval harness, which runs the same tools synchronously.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.graph.extractor import extract_learning_graph
from src.graph.retriever import ground_context
from src.harness import ExternalCallError, cost
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
    Modality,
    SessionTurn,
    WorkflowStep,
)
from src.tools import (
    diagnose_learner,
    generate_artifact,
    plan_workflow,
    update_learner_model,
)

app = FastAPI(title="Adaptive Learning Agent", version="0.1.0")
app.add_middleware(DemoTokenMiddleware)  # gates session endpoints if DEMO_TOKEN set
store = MemoryStore()
rate_limiter = RateLimiter()


@app.exception_handler(ExternalCallError)
def external_call_error_handler(request, exc: ExternalCallError):
    """
    Upstream (Anthropic API) failure after retries — surface it as a structured
    502 instead of an opaque 500. The SSE path handles this inline instead
    (an error event mid-stream), since headers are already sent by then.
    """
    return JSONResponse(status_code=502, content=exc.to_payload())

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
    domain_id: str
    # One of these must be set:
    source_text: str | None = None  # raw material to extract a graph from
    domain_title: str | None = None


class RespondRequest(BaseModel):
    correct: bool
    notes: str = ""


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/graphs")
def list_graphs():
    return {"graphs": store.list_graphs()}


@app.post("/sessions/start")
def start_session(req: StartSessionRequest, request: Request):
    # Demo guards: daily global budget, then per-IP creation rate limit.
    if daily_budget_exhausted():
        return budget_exhausted_response()
    if not rate_limiter.check(client_ip(request)):
        return rate_limited_response()

    # Account everything this request spends against the session's budget.
    with cost.meter() as session_meter:
        return _run_start(req, session_meter)


def _run_start(req: StartSessionRequest, session_meter: cost.CostMeter) -> JSONResponse:
    # 1. Get-or-extract the graph.
    graph: LearningGraph | None = None
    domain_path = Path("domains") / f"{req.domain_id}.md"
    if req.source_text:
        graph = extract_learning_graph(
            req.source_text, req.domain_title or req.domain_id, store
        )
    elif domain_path.exists():
        graph = extract_learning_graph(
            domain_path.read_text(),
            req.domain_title or req.domain_id.replace("_", " "),
            store,
        )
    else:
        # Fall back to a previously stored graph for this domain_id.
        for entry in store.list_graphs():
            if entry["domain_id"] == req.domain_id:
                graph = store.get_graph_by_source_hash(entry["source_hash"])
                break
    if graph is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No graph for domain '{req.domain_id}'. Pass source_text in the "
                f"request body or add domains/{req.domain_id}.md."
            ),
        )

    # 2. Get-or-create the learner.
    learner = store.get_learner(req.user_id, req.domain_id)
    if learner is None:
        learner = LearnerModel(user_id=req.user_id, domain_id=req.domain_id)
        store.save_learner(learner)

    # 3. ASSESS + PLAN.
    gap = diagnose_learner(learner, graph)
    workflow = plan_workflow(gap, learner, graph)

    # 4. GENERATE the first artifact (grounded in retrieved source passages).
    step = workflow.steps[0]
    concept = graph.node_by_id(step.concept_id)
    artifact = generate_artifact(
        step, concept, learner, source_context=ground_context(concept, graph, store)
    )

    session_id = uuid.uuid4().hex[:12]
    SESSIONS[session_id] = {
        "user_id": req.user_id,
        "domain_id": req.domain_id,
        "graph": graph,
        "learner": learner,
        "gap": gap,
        "workflow": workflow,
        "current_step_index": 0,
        "cost_usd": session_meter.total_usd,
    }

    return JSONResponse(
        {
            "session_id": session_id,
            "gap": gap.model_dump(mode="json"),
            "workflow": workflow.model_dump(mode="json"),
            "current_step": step.model_dump(mode="json"),
            "artifact": artifact.model_dump(mode="json"),
            "cost": _cost_summary(session_meter.total_usd),
        }
    )


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


@app.post("/sessions/start_stream")
def start_session_stream(req: StartSessionRequest, request: Request):
    """
    SSE variant of /sessions/start.

    Streams each agent-loop phase (assess → plan → generate) as it happens, so
    a UI can render incrementally. The final 'session_ready' event carries the
    session_id to use for subsequent /sessions/{id}/respond calls.
    """
    # Demo guards before opening the stream (same as /sessions/start).
    if daily_budget_exhausted():
        return budget_exhausted_response()
    if not rate_limiter.check(client_ip(request)):
        return rate_limited_response()

    def event_stream():
        # Accumulate this session's spend; the meter stays active for the whole
        # generator body, so every LLM call below counts toward the session.
        with cost.meter() as session_meter:
            try:
                # 1. Graph.
                domain_path = Path("domains") / f"{req.domain_id}.md"
                yield _sse_event("phase", {"name": "load_graph"})
                graph: LearningGraph | None = None
                if req.source_text:
                    graph = extract_learning_graph(
                        req.source_text, req.domain_title or req.domain_id, store
                    )
                elif domain_path.exists():
                    graph = extract_learning_graph(
                        domain_path.read_text(),
                        req.domain_title or req.domain_id.replace("_", " "),
                        store,
                    )
                else:
                    for entry in store.list_graphs():
                        if entry["domain_id"] == req.domain_id:
                            graph = store.get_graph_by_source_hash(entry["source_hash"])
                            break
                if graph is None:
                    yield _sse_event(
                        "error", {"message": f"No graph for domain '{req.domain_id}'."}
                    )
                    return
                yield _sse_event(
                    "graph", {"domain_id": graph.domain_id, "n_nodes": len(graph.nodes)}
                )

                # 2. Learner.
                learner = store.get_learner(req.user_id, req.domain_id)
                if learner is None:
                    learner = LearnerModel(user_id=req.user_id, domain_id=req.domain_id)
                    store.save_learner(learner)
                yield _sse_event("learner", {"learner": learner.model_dump(mode="json")})

                # 3. ASSESS.
                yield _sse_event("phase", {"name": "assess"})
                gap = diagnose_learner(learner, graph)
                yield _sse_event("gap", {"gap": gap.model_dump(mode="json")})

                # 4. PLAN.
                yield _sse_event("phase", {"name": "plan"})
                workflow = plan_workflow(gap, learner, graph)
                yield _sse_event(
                    "workflow", {"workflow": workflow.model_dump(mode="json")}
                )

                # 5. GENERATE first artifact.
                yield _sse_event("phase", {"name": "generate"})
                step = workflow.steps[0]
                concept = graph.node_by_id(step.concept_id)
                artifact = generate_artifact(
                    step, concept, learner, source_context=ground_context(concept, graph, store)
                )

                session_id = uuid.uuid4().hex[:12]
                SESSIONS[session_id] = {
                    "user_id": req.user_id,
                    "domain_id": req.domain_id,
                    "graph": graph,
                    "learner": learner,
                    "gap": gap,
                    "workflow": workflow,
                    "current_step_index": 0,
                    "cost_usd": session_meter.total_usd,
                }
                yield _sse_event(
                    "artifact",
                    {
                        "step": step.model_dump(mode="json"),
                        "artifact": artifact.model_dump(mode="json"),
                    },
                )
                yield _sse_event(
                    "session_ready",
                    {"session_id": session_id, "cost": _cost_summary(session_meter.total_usd)},
                )
            except ExternalCallError as e:
                yield _sse_event("error", e.to_payload())
            except Exception as e:
                yield _sse_event(
                    "error", {"message": str(e), "type": type(e).__name__}
                )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/sessions/{session_id}/respond")
def respond(session_id: str, req: RespondRequest):
    state = SESSIONS.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    graph: LearningGraph = state["graph"]
    workflow = state["workflow"]
    learner: LearnerModel = state["learner"]
    idx = state["current_step_index"]
    step: WorkflowStep = workflow.steps[idx]
    modality = step.modality if isinstance(step.modality, Modality) else Modality(step.modality)

    # OBSERVE + ADAPT.
    turn = SessionTurn(
        concept_id=step.concept_id,
        modality=modality,
        correct=req.correct,
        notes=req.notes,
    )
    learner = update_learner_model(learner, turn, store)
    state["learner"] = learner

    # Advance.
    next_idx = idx + 1
    if next_idx >= len(workflow.steps):
        return JSONResponse(
            {
                "session_id": session_id,
                "status": "workflow_complete",
                "learner": learner.model_dump(mode="json"),
                "note": "Call /sessions/start again to author a new workflow from the updated learner state.",
                "cost": _cost_summary(state.get("cost_usd", 0.0)),
            }
        )

    # Per-session budget cap: if this session has already spent its allowance,
    # terminate gracefully rather than generating another (paid) artifact.
    if state.get("cost_usd", 0.0) >= PER_SESSION_USD_CAP:
        return JSONResponse(
            {
                "session_id": session_id,
                "status": "session_budget_reached",
                "learner": learner.model_dump(mode="json"),
                "note": "This session reached its cost cap. Start a new session to continue.",
                "cost": _cost_summary(state.get("cost_usd", 0.0)),
            }
        )

    state["current_step_index"] = next_idx
    next_step = workflow.steps[next_idx]
    concept = graph.node_by_id(next_step.concept_id)
    with cost.meter() as step_meter:
        artifact = generate_artifact(
            next_step, concept, learner, source_context=ground_context(concept, graph, store)
        )
    state["cost_usd"] = state.get("cost_usd", 0.0) + step_meter.total_usd
    return JSONResponse(
        {
            "session_id": session_id,
            "status": "in_progress",
            "current_step": next_step.model_dump(mode="json"),
            "artifact": artifact.model_dump(mode="json"),
            "learner": learner.model_dump(mode="json"),
            "cost": _cost_summary(state["cost_usd"]),
        }
    )
