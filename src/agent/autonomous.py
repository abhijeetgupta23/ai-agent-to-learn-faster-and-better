"""
Autonomous orchestration mode: the model owns the loop.

Workflow mode (src/agent/loop.py + /sessions endpoints) is a fixed pipeline —
code chains the tools, the LLM fills in the decisions. This module is the
second orchestration mode: the same capabilities are exposed as REAL tool-use
tools (Anthropic `tools=` API) and the model decides which to call, in what
order, and when to stop — inside the same budgets, cost meter, and streaming
sink as workflow mode. The two modes share everything below the orchestrator,
so the eval harness can compare them on equal footing.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from src.graph.retriever import ground_context
from src.harness import cost
from src.harness.retry import call_with_retries
from src.llm import _THINKING, DEFAULT_MODEL, _thinking_sink, get_client
from src.memory.store import MemoryStore
from src.schemas import (
    LearnerModel,
    LearningGraph,
    Modality,
    SessionTurn,
    WorkflowStep,
)
from src.tools import diagnose_learner, generate_artifact, plan_workflow, update_learner_model

AGENT_MODEL = os.environ.get("ADAPTIVE_LEARNING_AGENT_MODEL", DEFAULT_MODEL)
# Per learner-visible turn, not per session — the orchestrator should rarely
# need more than diagnose + plan + teach (3).
MAX_TOOL_CALLS_PER_TURN = int(os.environ.get("ADAPTIVE_LEARNING_AGENT_MAX_TOOLS", "6"))

AGENT_SYSTEM = """\
You are an autonomous adaptive-tutor agent. Goal: move this learner toward
mastery of the subject as fast as possible, one lesson at a time.

You own the loop. There is no fixed pipeline — YOU decide which tools to call,
in what order, and when to stop. Guidance, not rules:

- Fresh session: usually diagnose first, optionally plan, then teach exactly
  ONE lesson and end your turn.
- When given the learner's answer: record_observation FIRST, then decide —
  advance to the next concept, re-teach the same one differently, backfill a
  prerequisite (re-diagnose if unsure), or declare the session complete if
  mastery has been reached.
- Teach AT MOST ONE artifact per turn. After a successful `teach`, end your
  turn with one or two sentences to the learner about what you chose and why.
- Don't call tools you don't need. Don't re-teach a concept the same way that
  already failed twice — change modality or back up the prerequisite chain.
- The subject map and learner profile arrive in the conversation; trust them.
"""

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "diagnose",
        "description": (
            "Estimate the learner's most valuable next concept from their profile "
            "and the subject map. Returns a GapEstimate (target concept, suggested "
            "difficulty, confidence, rationale). Call when you're unsure what to "
            "teach next or the learner's state changed materially."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "plan_lessons",
        "description": (
            "Author a 3-5 step teaching workflow for the most recent diagnosis "
            "(requires a prior `diagnose` this session). Returns the workflow with "
            "modality and pedagogy principle per step. Optional — you may teach "
            "directly from a diagnosis when one step is obviously right."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "teach",
        "description": (
            "Generate and deliver one teaching artifact to the learner. This is the "
            "only tool that reaches the learner — call it exactly once per turn, "
            "then end your turn."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "concept_id": {"type": "string", "description": "Concept id from the subject map."},
                "modality": {"type": "string", "enum": ["reading", "interactive", "socratic"]},
                "objective": {"type": "string", "description": "What this lesson should achieve."},
                "pedagogy_principle": {
                    "type": "string",
                    "description": "Named principle driving the choice, e.g. desirable_difficulty, worked_example, spaced_repetition, interleaving, elaboration.",
                },
            },
            "required": ["concept_id", "modality", "objective", "pedagogy_principle"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_observation",
        "description": (
            "Integrate the learner's answer to the last lesson into their profile "
            "(mastery, struggles, difficulty). Call this before deciding what to do "
            "next whenever you've been given a new answer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "correct": {"type": "boolean"},
                "notes": {"type": "string", "description": "The learner's own words, if any."},
            },
            "required": ["correct"],
            "additionalProperties": False,
        },
    },
    {
        "name": "view_learner",
        "description": "Re-read the learner's current profile (mastered, struggling, difficulty, history).",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def kickoff_message(learner: LearnerModel, graph: LearningGraph) -> str:
    """The first user turn: everything the agent needs to start deciding."""
    concepts = [
        {
            "id": n.concept_id,
            "name": n.name,
            "difficulty": n.difficulty,
            "prerequisites": n.prerequisites,
        }
        for n in graph.nodes
    ]
    return (
        f"SUBJECT MAP ({graph.domain_title}):\n{json.dumps(concepts, indent=1)}\n\n"
        f"LEARNER PROFILE:\n{learner.model_dump_json(indent=1)}\n\n"
        "Begin the session: decide what this learner needs and teach one lesson."
    )


def observation_message(correct: bool, notes: str) -> str:
    return (
        f"The learner answered the last lesson. correct={correct}"
        + (f', notes="{notes}"' if notes else "")
        + "\nDecide what happens next."
    )


def _usage(response) -> dict:
    u = response.usage
    return {
        "input_tokens": getattr(u, "input_tokens", 0),
        "output_tokens": getattr(u, "output_tokens", 0),
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0),
    }


def _execute_tool(name: str, args: dict, state: dict, emit: Callable[[str, dict], None]) -> Any:
    """Run one tool against the session state. Returns the payload sent back to
    the model (kept compact — the learner-facing artifact goes out via emit,
    not into the orchestrator's context)."""
    learner: LearnerModel = state["learner"]
    graph: LearningGraph = state["graph"]
    store: MemoryStore | None = state.get("store")

    if name == "diagnose":
        gap = diagnose_learner(learner, graph)
        state["last_gap"] = gap
        emit("gap", {"gap": gap.model_dump(mode="json")})
        return gap.model_dump(mode="json")

    if name == "plan_lessons":
        gap = state.get("last_gap")
        if gap is None:
            raise ValueError("No diagnosis yet this session — call `diagnose` first.")
        workflow = plan_workflow(gap, learner, graph)
        state["last_workflow"] = workflow
        emit("workflow", {"workflow": workflow.model_dump(mode="json")})
        return workflow.model_dump(mode="json")

    if name == "teach":
        concept = graph.node_by_id(args["concept_id"])
        if concept is None:
            raise ValueError(
                f"Unknown concept_id '{args['concept_id']}' — use an id from the subject map."
            )
        step = WorkflowStep(
            step_number=state.get("steps_taught", 0) + 1,
            concept_id=concept.concept_id,
            modality=Modality(args["modality"]),
            objective=args["objective"],
            pedagogy_principle=args["pedagogy_principle"],
        )
        artifact = generate_artifact(
            step, concept, learner,
            source_context=ground_context(concept, graph, store, learner=learner),
        )
        state["steps_taught"] = step.step_number
        state["current_step"] = step
        emit("artifact", {
            "step": step.model_dump(mode="json"),
            "artifact": artifact.model_dump(mode="json"),
        })
        # Teaching chart (model-written code, hosted sandbox), emitted after the lesson.
        if artifact.type == "reading":
            from src.tools.charts import chart_data_url

            durl = chart_data_url(concept, artifact.title, step.objective)
            if durl:
                emit("chart", {"step_number": step.step_number, "chart": durl})
        return {
            "status": "delivered_to_learner",
            "artifact_type": artifact.type,
            "concept_id": concept.concept_id,
        }

    if name == "record_observation":
        step: WorkflowStep | None = state.get("current_step")
        if step is None:
            raise ValueError("No lesson has been taught yet — nothing to observe.")
        turn = SessionTurn(
            concept_id=step.concept_id,
            modality=step.modality,
            correct=bool(args["correct"]),
            notes=args.get("notes", ""),
        )
        state["learner"] = update_learner_model(learner, turn, store)
        emit("learner", {"learner": state["learner"].model_dump(mode="json")})
        return {
            "mastered_concepts": state["learner"].mastered_concepts,
            "struggling_concepts": state["learner"].struggling_concepts,
            "difficulty_level": state["learner"].difficulty_level,
        }

    if name == "view_learner":
        return learner.model_dump(mode="json")

    raise ValueError(f"Unknown tool: {name}")


def run_agent_turn(state: dict, user_message: str, emit: Callable[[str, dict], None]) -> str:
    """
    One learner-visible turn: append the user message, then let the model run
    its tool loop until it stops talking to tools and talks to the learner.

    Returns the model's final text. Thinking/text deltas stream to the active
    thinking sink (same contextvar workflow mode uses), tool activity and
    results stream via `emit`.
    """
    client = get_client()
    messages: list = state["messages"]
    messages.append({"role": "user", "content": user_message})
    sink = _thinking_sink.get()

    tool_calls = 0
    final_text = ""
    while True:
        def _call():
            with client.messages.stream(
                model=AGENT_MODEL,
                max_tokens=6000,
                thinking=_THINKING,
                system=AGENT_SYSTEM,
                tools=TOOL_SCHEMAS,
                messages=messages,
            ) as s:
                for event in s:
                    if sink is None or event.type != "content_block_delta":
                        continue
                    if event.delta.type == "thinking_delta" and event.delta.thinking:
                        sink("thinking", event.delta.thinking)
                    elif event.delta.type == "text_delta" and event.delta.text:
                        sink("text", event.delta.text)
                return s.get_final_message()

        response = call_with_retries(_call, label="llm:agent_orchestrator")
        cost.record(AGENT_MODEL, _usage(response))
        # Append raw blocks — thinking blocks must round-trip verbatim.
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            final_text = "".join(b.text for b in response.content if b.type == "text")
            break

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_calls += 1
            emit("tool_call", {"tool": block.name, "args": dict(block.input or {})})
            try:
                out = _execute_tool(block.name, dict(block.input or {}), state, emit)
                content = json.dumps(out)[:4000]
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": content}
                )
                emit("tool_result", {"tool": block.name, "ok": True})
            except Exception as e:  # surfaced to the model so it can adapt
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"error: {e}",
                        "is_error": True,
                    }
                )
                emit("tool_result", {"tool": block.name, "ok": False, "error": str(e)})
        user_content: list = results
        if tool_calls >= MAX_TOOL_CALLS_PER_TURN:
            user_content = results + [
                {
                    "type": "text",
                    "text": "[tool budget for this turn is exhausted — wrap up in text now]",
                }
            ]
        messages.append({"role": "user", "content": user_content})

    if final_text:
        emit("agent_text", {"text": final_text})
    return final_text
