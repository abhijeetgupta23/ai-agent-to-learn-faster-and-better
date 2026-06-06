"""
Single-loop agent: ASSESS → PLAN → GENERATE → OBSERVE → ADAPT.

The five tools (§6 of HANDOFF.md) are wired here as native Python functions
called directly from the loop — Programmatic Tool Calling in spirit: the tools
are functions in the execution namespace, the LLM authors the workflow that
chains them. The LLM is the workflow author; this loop is the executor.

For V1, the workflow shape is fixed (diagnose → plan → for each step:
generate → observe). The LLM's "agentic" decision-making is concentrated in
the plan_workflow step, which authors the step sequence + modality choice on
the fly based on learner state. That is where the adaptive intelligence lives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterator

from src.memory.store import MemoryStore
from src.schemas import (
    Artifact,
    GapEstimate,
    LearnerModel,
    LearningGraph,
    SessionTurn,
    Workflow,
    WorkflowStep,
)
from src.tools import (
    diagnose_learner,
    generate_artifact,
    plan_workflow,
    update_learner_model,
)


@dataclass
class AgentEvent:
    """One event in the loop's output stream — what the server forwards as SSE."""

    type: str  # 'phase' | 'gap' | 'workflow' | 'artifact' | 'observation' | 'learner_update' | 'done' | 'error'
    payload: dict = field(default_factory=dict)


# Responses to interactive artifacts are gathered by an injected callback. The
# server provides one that holds the loop until the learner POSTs an answer.
# The eval harness provides a synthetic one.
LearnerResponseFn = Callable[[Artifact, WorkflowStep], SessionTurn]


def run_session(
    learner: LearnerModel,
    graph: LearningGraph,
    *,
    on_learner_response: LearnerResponseFn,
    store: MemoryStore | None = None,
    max_workflow_iterations: int = 1,
) -> Iterator[AgentEvent]:
    """
    Run one full teaching session and yield events for streaming.

    The loop:
      1. ASSESS — diagnose_learner returns the gap.
      2. PLAN   — plan_workflow authors a 3-5 step sequence + modality.
      3. For each step:
         GENERATE   — generate_artifact builds the teaching artifact.
         OBSERVE    — on_learner_response captures the learner turn.
         ADAPT      — update_learner_model persists the change.
      4. (Optionally loop back to PLAN with the new learner state.)
    """
    try:
        for _ in range(max_workflow_iterations):
            yield AgentEvent("phase", {"name": "assess"})
            gap: GapEstimate = diagnose_learner(learner, graph)
            yield AgentEvent("gap", {"gap": gap.model_dump(mode="json")})

            yield AgentEvent("phase", {"name": "plan"})
            workflow: Workflow = plan_workflow(gap, learner, graph)
            yield AgentEvent("workflow", {"workflow": workflow.model_dump(mode="json")})

            for step in workflow.steps:
                concept = graph.node_by_id(step.concept_id)
                if concept is None:
                    yield AgentEvent(
                        "error",
                        {"message": f"Step references unknown concept {step.concept_id}"},
                    )
                    return

                yield AgentEvent(
                    "phase", {"name": "generate", "step": step.step_number}
                )
                artifact = generate_artifact(step, concept, learner)
                yield AgentEvent(
                    "artifact",
                    {
                        "step": step.step_number,
                        "concept_id": step.concept_id,
                        "modality": step.modality.value,
                        "artifact": artifact.model_dump(mode="json"),
                    },
                )

                yield AgentEvent("phase", {"name": "observe", "step": step.step_number})
                turn = on_learner_response(artifact, step)
                yield AgentEvent("observation", {"turn": turn.model_dump(mode="json")})

                yield AgentEvent("phase", {"name": "adapt", "step": step.step_number})
                learner = update_learner_model(learner, turn, store)
                yield AgentEvent(
                    "learner_update",
                    {"learner": learner.model_dump(mode="json")},
                )

        yield AgentEvent("done", {"learner": learner.model_dump(mode="json")})
    except Exception as e:
        yield AgentEvent("error", {"message": str(e), "type": type(e).__name__})
