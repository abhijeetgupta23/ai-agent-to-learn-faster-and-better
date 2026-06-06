"""Generate the teaching artifact in the chosen modality."""

from __future__ import annotations

from src.llm import complete_json
from src.schemas import (
    Artifact,
    ConceptNode,
    InteractiveArtifact,
    LearnerModel,
    Modality,
    ReadingArtifact,
    SocraticArtifact,
    WorkflowStep,
)

READING_SYSTEM = """\
You are an expert tutor writing a short reading passage (300-500 words) that
teaches one concept clearly. Use a worked example or analogy if it helps.
Calibrate vocabulary to the learner's difficulty_level (1=novice, 5=expert).
Include 3-5 key takeaways.
"""

INTERACTIVE_SYSTEM = """\
You are an expert tutor writing a short interactive exercise: 3-5 questions
that test understanding of one concept. Use multiple-choice when there are
clear distractors that surface common misconceptions; use free-response when
the answer is a short derivation or definition. Every question must have an
`explanation` field — this is what the learner sees if they get it wrong.
"""

SOCRATIC_SYSTEM = """\
You are an expert tutor designing a Socratic dialogue script. The dialogue
should consist of 4-7 alternating turns where the AGENT asks a guiding question
and a LEARNER_PROMPT slot indicates what the learner is asked to respond.
The dialogue must lead the learner to an INSIGHT — the target_insight — not
just to a fact. Surface and challenge common misconceptions explicitly.
"""


def generate_artifact(
    step: WorkflowStep,
    concept: ConceptNode,
    learner: LearnerModel,
) -> Artifact:
    modality = step.modality if isinstance(step.modality, Modality) else Modality(step.modality)
    user_context = (
        f"Concept to teach:\n{concept.model_dump_json(indent=2)}\n\n"
        f"Step objective: {step.objective}\n"
        f"Pedagogy principle: {step.pedagogy_principle}\n"
        f"Learner difficulty level: {learner.difficulty_level}\n"
        f"Learner modality preference: {learner.modality_preference.value}\n"
    )

    if modality == Modality.READING:
        return complete_json(READING_SYSTEM, user_context, ReadingArtifact, max_tokens=3000)
    if modality == Modality.INTERACTIVE:
        return complete_json(
            INTERACTIVE_SYSTEM, user_context, InteractiveArtifact, max_tokens=3000
        )
    if modality == Modality.SOCRATIC:
        return complete_json(SOCRATIC_SYSTEM, user_context, SocraticArtifact, max_tokens=3000)
    raise ValueError(f"Unknown modality: {modality}")
