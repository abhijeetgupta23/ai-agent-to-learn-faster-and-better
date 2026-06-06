"""
Judge 1: did the generated lesson target the diagnosed gap?

Question: given the diagnosed target concept, does the workflow actually focus
on that concept (vs. drifting to a tangentially related one), and do the
pedagogy principles cited make sense for closing this kind of gap?

Returns a score in [0, 1] and a rationale that names the evidence.
"""

from __future__ import annotations

from src.llm import complete_json
from src.schemas import GapEstimate, JudgeResult, LearningGraph, Workflow

SYSTEM = """\
You are an evaluator scoring whether a generated teaching workflow targets the
diagnosed knowledge gap.

Score in [0,1]:
  1.0 — workflow's target_concept_id matches the gap, ALL steps relate to that
        concept or its prerequisites, pedagogy principles are appropriate.
  0.7 — target matches, most steps are on-topic, principles mostly appropriate.
  0.4 — target matches but workflow drifts to tangential concepts, OR target
        matches but pedagogy principles are mismatched (e.g. spaced_repetition
        on a brand-new concept).
  0.0 — target does not match the gap.

In your rationale: name the specific steps you scored on, and cite which
pedagogy principle is or isn't appropriate.
"""


def judge_gap_to_pedagogy(
    gap: GapEstimate,
    workflow: Workflow,
    graph: LearningGraph,
) -> JudgeResult:
    user = (
        f"Diagnosed gap:\n{gap.model_dump_json(indent=2)}\n\n"
        f"Generated workflow:\n{workflow.model_dump_json(indent=2)}\n\n"
        f"Available concepts in graph: "
        f"{[n.concept_id for n in graph.nodes]}\n\n"
        "Score the workflow on whether it targets the diagnosed gap. "
        f"Return a JudgeResult with judge_name='gap_to_pedagogy'."
    )
    result = complete_json(SYSTEM, user, JudgeResult, max_tokens=1500)
    result.judge_name = "gap_to_pedagogy"
    return result
