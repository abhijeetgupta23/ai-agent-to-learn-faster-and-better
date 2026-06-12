"""
Judge 3: did difficulty adjust correctly given performance?

This judge inspects the diagnosed difficulty against the learner's current
difficulty_level and expected band, and checks the trajectory implied by the
session_history (struggling → step down, mastery → step up).
"""

from __future__ import annotations

from src.llm import JUDGE_MODEL, complete_json
from src.schemas import GapEstimate, JudgeResult, LearnerModel

SYSTEM = """\
You are an evaluator scoring whether the suggested difficulty level adapts
correctly to the learner's recent performance.

Adaptive-difficulty principles:
  - If the learner has 2+ struggling concepts at the current difficulty_level,
    suggested_difficulty should be <= difficulty_level.
  - If the learner has 3+ recent CORRECT turns at the current difficulty_level,
    suggested_difficulty may step up (difficulty_level + 1) IF the concept's
    intrinsic difficulty supports it.
  - Otherwise, suggested_difficulty should be at or within 1 of difficulty_level.
  - suggested_difficulty must stay in [1, 5] — no trivializing, no overwhelming.

Score in [0,1]:
  1.0 — suggested difficulty is exactly right per the principles above.
  0.7 — suggested difficulty is within 1 of right per the principles.
  0.3 — suggested difficulty violates a principle (e.g. raised difficulty for
        a struggling learner).
  0.0 — suggested difficulty is outside [1, 5] or wildly mismatched.

Cite the specific learner-state signal in your rationale.
"""


def judge_adaptive_progression(
    gap: GapEstimate,
    learner: LearnerModel,
    expected_band: tuple[int, int],
) -> JudgeResult:
    n_struggling = len(learner.struggling_concepts)
    recent = learner.session_history[-5:]
    recent_correct = sum(1 for t in recent if t.correct is True)
    in_band = expected_band[0] <= gap.suggested_difficulty <= expected_band[1]

    user = (
        f"Gap estimate:\n{gap.model_dump_json(indent=2)}\n\n"
        f"Learner difficulty_level: {learner.difficulty_level}\n"
        f"Struggling concepts: {learner.struggling_concepts} "
        f"({n_struggling} concepts)\n"
        f"Mastered concepts: {learner.mastered_concepts}\n"
        f"Recent turns ({len(recent)} total): {recent_correct} correct\n"
        f"Expected difficulty band for this case: {expected_band}\n"
        f"Suggested difficulty is in expected band: {in_band}\n\n"
        "Score the adaptive-progression decision. Return a JudgeResult with "
        "judge_name='adaptive_progression'."
    )
    result = complete_json(
        SYSTEM, user, JudgeResult, label="judge:adaptive_progression", model=JUDGE_MODEL, max_tokens=3000
    )
    result.judge_name = "adaptive_progression"
    return result
