"""
Judge 2: was the chosen modality right for this learner's profile?

Modality routing is the central differentiator vs. existing edtech, so this
judge is load-bearing. It checks the chosen modality against learner state
using a small ruleset, then asks the LLM to weigh edge cases.
"""

from __future__ import annotations

from src.llm import complete_json
from src.schemas import JudgeResult, LearnerModel, Modality, Workflow

SYSTEM = """\
You are an evaluator scoring whether the chosen teaching modality is right
for this learner.

Modality routing principles:
  - 'socratic' is the RIGHT call when the learner is STRUGGLING with the target
    concept (target is in struggling_concepts) — dialogue surfaces misconceptions
    that re-reading hides. Also right for concepts known to harbor common
    misconceptions.
  - 'interactive' (quiz/scenario) is the RIGHT call for procedural skills where
    the learner has seen the material once and needs practice (retrieval >
    re-reading; desirable difficulty).
  - 'reading' is the RIGHT call for new conceptual material the learner hasn't
    seen, especially when modality_preference is reading.

Score in [0,1]:
  1.0 — modality is the textbook-correct choice per the rules above; rationale
        in the workflow cites learner state to justify it.
  0.7 — modality is defensible (one of two reasonable choices) and rationale
        is sound.
  0.3 — modality is plausible but a clearly better choice was available
        (e.g. learner is struggling and got 'reading' instead of 'socratic').
  0.0 — modality is wrong (e.g. brand-new concept got 'socratic'; struggling
        concept got more reading).

In your rationale, name the specific learner-state signal you weighed.
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
        "Score the modality choice. Return a JudgeResult with "
        "judge_name='modality_fit'."
    )
    result = complete_json(SYSTEM, user, JudgeResult, max_tokens=1500)
    result.judge_name = "modality_fit"
    return result
