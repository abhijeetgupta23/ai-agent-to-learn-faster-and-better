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

import contextvars
import json
import queue
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.graph.extractor import extract_learning_graph
from src.graph.retriever import ground_context
from src.harness import ExternalCallError, cost
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
    # Optional: seed the learner state (mastered/struggling/difficulty/history)
    # so a demo can reproduce a specific adaptive decision (e.g. a prereq gap).
    learner: dict | None = None


def _seeded_learner(req: "StartSessionRequest") -> LearnerModel | None:
    """Build a LearnerModel from an explicit seed in the request, if present."""
    if not req.learner:
        return None
    seed = req.learner
    return LearnerModel(
        user_id=req.user_id,
        domain_id=req.domain_id,
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
            domain_path.read_text(encoding="utf-8"),
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

    # 2. Get-or-create the learner (or use an explicit seed).
    learner = _seeded_learner(req)
    if learner is not None:
        store.save_learner(learner)
    else:
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
        step, concept, learner, source_context=ground_context(concept, graph, store, learner=learner)
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
        # Per-session spend accumulator. Deliberately NOT cost.meter():
        # Starlette iterates this sync generator via a threadpool where each
        # next() runs in a fresh context copy, so a contextvar set here would
        # not survive across iterations. The meter object is passed explicitly
        # to each phase worker instead (see _thinking_events).
        session_meter = cost.CostMeter()
        try:
            # 1. Graph.
            domain_path = Path("domains") / f"{req.domain_id}.md"
            yield _sse_event("phase", {"name": "load_graph"})
            graph: LearningGraph | None = None
            if req.source_text:
                graph = yield from _thinking_events(
                    "load_graph",
                    lambda: extract_learning_graph(
                        req.source_text, req.domain_title or req.domain_id, store
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
                    "error", {"message": f"No graph for domain '{req.domain_id}'."}
                )
                return
            yield _sse_event(
                "graph",
                {
                    "domain_id": graph.domain_id,
                    "n_nodes": len(graph.nodes),
                    # Compact node list so the UI can draw the live concept
                    # graph and animate the agent's decisions onto it.
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

            # 2. Learner (or an explicit seed, for reproducible demo decisions).
            learner = _seeded_learner(req)
            if learner is not None:
                store.save_learner(learner)
            else:
                learner = store.get_learner(req.user_id, req.domain_id)
                if learner is None:
                    learner = LearnerModel(
                        user_id=req.user_id, domain_id=req.domain_id
                    )
                    store.save_learner(learner)
            yield _sse_event("learner", {"learner": learner.model_dump(mode="json")})

            # 3. ASSESS.
            yield _sse_event("phase", {"name": "assess"})
            gap = yield from _thinking_events(
                "assess", lambda: diagnose_learner(learner, graph), session_meter
            )
            yield _sse_event("gap", {"gap": gap.model_dump(mode="json")})

            # 4. PLAN.
            yield _sse_event("phase", {"name": "plan"})
            workflow = yield from _thinking_events(
                "plan", lambda: plan_workflow(gap, learner, graph), session_meter
            )
            yield _sse_event(
                "workflow", {"workflow": workflow.model_dump(mode="json")}
            )

            # 5. GENERATE first artifact.
            yield _sse_event("phase", {"name": "generate"})
            step = workflow.steps[0]
            concept = graph.node_by_id(step.concept_id)
            artifact = yield from _thinking_events(
                "generate",
                lambda: generate_artifact(
                    step,
                    concept,
                    learner,
                    source_context=ground_context(concept, graph, store, learner=learner),
                ),
                session_meter,
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
            next_step, concept, learner, source_context=ground_context(concept, graph, store, learner=learner)
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
            if req.source_text:
                graph = yield from _thinking_events(
                    "load_graph",
                    lambda: extract_learning_graph(
                        req.source_text, req.domain_title or req.domain_id, store
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

            learner = _seeded_learner(req)
            if learner is not None:
                store.save_learner(learner)
            else:
                learner = store.get_learner(req.user_id, req.domain_id)
                if learner is None:
                    learner = LearnerModel(user_id=req.user_id, domain_id=req.domain_id)
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
                "domain_id": req.domain_id,
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
            yield _sse_event("error", e.to_payload())
        except Exception as e:
            yield _sse_event("error", {"message": str(e), "type": type(e).__name__})

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
            yield _sse_event("error", e.to_payload())
        except Exception as e:
            yield _sse_event("error", {"message": str(e), "type": type(e).__name__})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
