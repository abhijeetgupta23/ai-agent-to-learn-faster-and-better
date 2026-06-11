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

# Appended to the system prompt when source passages are supplied. This is what
# turns generation from "teach from memory" into grounded, source-faithful
# generation.
GROUNDING_CLAUSE = """\

GROUNDING — IMPORTANT:
You are given SOURCE MATERIAL below. Base the lesson on it. Specifically:
  - Every domain-specific claim, example, name, statistic, or term you teach
    must be supported by the source material. Do not introduce facts or
    named examples that the source does not contain.
  - You MAY add everyday analogies and explanatory scaffolding to make the
    source's ideas clear — that's good teaching — but the substantive content
    stays anchored to the source.
  - If the source is thin on a point, teach what it does say rather than
    inventing specifics to fill the gap.
"""


def generate_artifact(
    step: WorkflowStep,
    concept: ConceptNode,
    learner: LearnerModel,
    source_context: str | None = None,
    *,
    wrap_up: bool = False,
) -> Artifact:
    """
    Generate the teaching artifact for one step.

    If `source_context` is provided (retrieved passages from the original source
    material), generation is *grounded*: the lesson is built from real source
    text rather than the model's parametric memory. When it's None, behaviour is
    unchanged (ungrounded generation from the concept description).

    `wrap_up=True` is set by the agent loop when this is the last step the
    session's iteration budget allows (src/harness/limits.py): the artifact
    should consolidate and close out rather than open new threads.
    """
    modality = step.modality if isinstance(step.modality, Modality) else Modality(step.modality)
    user_context = (
        f"Concept to teach:\n{concept.model_dump_json(indent=2)}\n\n"
        f"Step objective: {step.objective}\n"
        f"Pedagogy principle: {step.pedagogy_principle}\n"
        f"Learner difficulty level: {learner.difficulty_level}\n"
        f"Learner modality preference: {learner.modality_preference.value}\n"
    )
    if wrap_up:
        user_context += (
            "\nSESSION WRAP-UP: this is the final artifact of the session "
            "(iteration budget reached). Consolidate what has been covered, "
            "close with a brief summary, and do not open new threads or "
            "tee up further exercises.\n"
        )
    grounding = ""
    if source_context:
        user_context += f"\nSOURCE MATERIAL (ground the lesson in this):\n---\n{source_context}\n---\n"
        grounding = GROUNDING_CLAUSE

    label_suffix = ":grounded" if source_context else ""
    if modality == Modality.READING:
        return complete_json(
            READING_SYSTEM + grounding, user_context, ReadingArtifact,
            label=f"generate:reading{label_suffix}", max_tokens=5000,
        )
    if modality == Modality.INTERACTIVE:
        return complete_json(
            INTERACTIVE_SYSTEM + grounding, user_context, InteractiveArtifact,
            label=f"generate:interactive{label_suffix}", max_tokens=5000,
        )
    if modality == Modality.SOCRATIC:
        return complete_json(
            SOCRATIC_SYSTEM + grounding, user_context, SocraticArtifact,
            label=f"generate:socratic{label_suffix}", max_tokens=5000,
        )
    raise ValueError(f"Unknown modality: {modality}")
