"""
Judge 2: was the chosen modality right for this learner's profile?

Modality routing is the central differentiator vs. existing edtech, so this
judge is load-bearing. It checks the chosen modality against learner state
using a small ruleset, then asks the LLM to weigh edge cases.
"""

from __future__ import annotations

from src.llm import JUDGE_MODEL, complete_json
from src.schemas import JudgeResult, LearnerModel, Modality, Workflow

SYSTEM = """\
You are an evaluator deciding whether the chosen teaching modality is a
defensible call for this learner. Return a BINARY verdict, not a rating.

Modality routing principles:
  - 'socratic' is RIGHT when the learner is STRUGGLING with the target concept
    (target in struggling_concepts), or the concept harbors common
    misconceptions — dialogue surfaces what re-reading hides.
  - 'interactive' (quiz/scenario/problem set) is RIGHT for a procedural skill the
    learner has seen and needs to PRACTICE (retrieval beats re-reading).
  - 'reading' is RIGHT for NEW conceptual material the learner hasn't seen,
    especially when modality_preference is reading.

Verdict (choose exactly one):
  - "pass" — the modality is the textbook-correct choice, OR a defensible one of
    two reasonable choices for this learner state. Do NOT fail a defensible call.
  - "fail" — the modality is the clearly wrong call: a distinctly better choice
    was available, or it is a named anti-pattern (a struggling concept given more
    reading; a brand-new concept opened with socratic).
  - "abstain" — genuinely too close to call even after applying the rules, or the
    learner state is insufficient to decide. Use sparingly.

Anchored examples:
  - struggling with target + got 'socratic'      -> pass (textbook).
  - struggling with target + got 'reading'       -> fail (anti-pattern).
  - brand-new concept + got 'reading'            -> pass (textbook).
  - brand-new concept + got 'socratic'           -> fail (no misconception yet).
  - a new concept the learner HAS the prerequisite for, taught 'interactive' to
    practice it -> pass (reading-first and practice-first are both reasonable).

modality_preference is a tie-breaker, not an override — demonstrated struggle
outranks stated preference. In your rationale, name the learner-state signal you
weighed, then give the verdict.
"""


def judge_modality_fit(
    workflow: Workflow,
    learner: LearnerModel,
    target_concept_id: str,
) -> JudgeResult:
    modality = workflow.modality.value if isinstance(workflow.modality, Modality) else workflow.modality
    is_struggling = target_concept_id in learner.struggling_concepts
    is_mastered = target_concept_id in learner.mastered_concepts
    user = (
        f"Workflow primary modality: {modality}\n"
        f"Workflow rationale: {workflow.rationale}\n\n"
        f"Target concept: {target_concept_id}\n"
        f"Learner is_struggling_with_target: {is_struggling}\n"
        f"Learner already_mastered_target: {is_mastered}\n"
        f"Learner modality_preference: {learner.modality_preference.value}\n"
        f"Learner difficulty_level: {learner.difficulty_level}\n"
        f"Mastered: {learner.mastered_concepts}\n"
        f"Struggling: {learner.struggling_concepts}\n\n"
        "Decide the modality choice. Return a JudgeResult with a binary "
        "verdict (pass / fail / abstain) and judge_name='modality_fit'."
    )
    result = complete_json(
        SYSTEM, user, JudgeResult, label="judge:modality_fit", model=JUDGE_MODEL,
        max_tokens=3000, deterministic=True,
    )
    result.judge_name = "modality_fit"
    return result
