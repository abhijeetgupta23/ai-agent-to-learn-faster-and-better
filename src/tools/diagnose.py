"""Diagnose the learner's current knowledge gap."""

from __future__ import annotations

from src.llm import complete_json
from src.schemas import GapEstimate, LearnerModel, LearningGraph

DIAGNOSE_SYSTEM = """\
You are an expert tutor. Given a learner's current state and a learning graph,
identify the single concept the learner should focus on NEXT.

Decision rules:
  1. If the learner has unresolved prerequisite gaps, target the deepest
     unresolved prerequisite first.
  2. Otherwise, target the lowest-difficulty unmastered concept whose
     prerequisites are all mastered.
  3. If a struggling concept exists, target it ONLY if its prerequisites are
     mastered — otherwise resolve the prerequisite first.

Set suggested_difficulty to one of:
  - the learner's current difficulty_level (steady)
  - difficulty_level - 1 (if learner is struggling with multiple concepts)
  - difficulty_level + 1 (if learner just mastered an adjacent concept at the
    current level)

Confidence reflects how clearly the rules point at one target (1.0 = unambiguous,
0.5 = several plausible targets, < 0.5 = guessing).
"""


def diagnose_learner(learner: LearnerModel, graph: LearningGraph) -> GapEstimate:
    user = (
        f"Learning graph:\n{graph.model_dump_json(indent=2)}\n\n"
        f"Learner model:\n{learner.model_dump_json(indent=2)}\n\n"
        "Produce a GapEstimate."
    )
    gap = complete_json(DIAGNOSE_SYSTEM, user, GapEstimate, label="diagnose", max_tokens=5000)
    # Validate target exists in graph.
    if graph.node_by_id(gap.target_concept_id) is None:
        raise ValueError(
            f"Diagnosed target '{gap.target_concept_id}' is not in graph "
            f"(known: {[n.concept_id for n in graph.nodes]})."
        )
    return gap
