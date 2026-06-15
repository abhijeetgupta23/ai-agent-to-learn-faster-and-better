"""
Judge 1: did the generated lesson target the diagnosed gap?

Question: given the diagnosed target concept, does the workflow actually focus
on that concept (vs. drifting to a tangentially related one), and do the
pedagogy principles cited make sense for closing this kind of gap?

Returns a score in [0, 1] and a rationale that names the evidence.
"""

from __future__ import annotations

from src.llm import JUDGE_MODEL, complete_json
from src.schemas import GapEstimate, JudgeResult, LearningGraph, Workflow

SYSTEM = """\
You are an evaluator deciding whether a generated teaching workflow targets the
diagnosed knowledge gap. Return a BINARY verdict, not a rating.

Verdict (choose exactly one):
  - "pass" — the workflow's target_concept_id matches the gap, its steps stay on
    that concept or its prerequisites, and the pedagogy principles are
    appropriate. Minor, well-motivated drift (e.g. one interleaving step with a
    related concept) is still a pass.
  - "fail" — the target does NOT match the gap, OR the workflow drifts
    substantially to tangential concepts, OR a pedagogy principle is clearly
    mismatched (e.g. spaced_repetition on a brand-new concept the learner has
    never seen).
  - "abstain" — genuinely borderline, or not enough information to decide. Use
    sparingly.

In your rationale: name the specific steps you weighed and cite which pedagogy
principle is or isn't appropriate, then give the verdict.
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
        "Decide whether the workflow targets the diagnosed gap. Return a "
        "JudgeResult with a binary verdict (pass / fail / abstain) and "
        "judge_name='gap_to_pedagogy'."
    )
    result = complete_json(
        SYSTEM, user, JudgeResult, label="judge:gap_to_pedagogy", model=JUDGE_MODEL,
        max_tokens=3000, deterministic=True,
    )
    result.judge_name = "gap_to_pedagogy"
    return result
