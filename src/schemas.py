"""
Pydantic schemas for the adaptive-learning-agent.

Every tool call returns one of these. The agent loop fails fast on validation
errors rather than swallowing malformed LLM output.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pedagogy primitives — grounded in named learning-science principles.
# References:
#   - Ebbinghaus (1885), Cepeda et al. (2008) — spaced repetition
#   - Rohrer & Taylor (2007) — interleaving
#   - Bjork & Bjork (2011) — desirable difficulties
#   - Sweller (1988) — cognitive load theory
# ---------------------------------------------------------------------------


class Modality(str, Enum):
    READING = "reading"
    INTERACTIVE = "interactive"  # quiz, scenario, problem set
    SOCRATIC = "socratic"  # dialogue-driven inquiry


class RelationshipType(str, Enum):
    PREREQUISITE = "prerequisite"
    RELATED = "related"
    INTERLEAVE_WITH = "interleave_with"


class ConceptNode(BaseModel):
    concept_id: str
    name: str
    description: str
    difficulty: int = Field(ge=1, le=5)
    prerequisites: list[str] = Field(default_factory=list)
    modality_hints: list[Modality] = Field(default_factory=list)
    spaced_repetition_interval_days: int | None = None


class LearningEdge(BaseModel):
    source: str
    target: str
    relationship_type: RelationshipType
    pedagogy_metadata: dict = Field(default_factory=dict)
    spacing_days: int | None = None


class LearningGraph(BaseModel):
    domain_id: str
    domain_title: str
    source_hash: str
    nodes: list[ConceptNode]
    edges: list[LearningEdge]
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def node_by_id(self, concept_id: str) -> ConceptNode | None:
        return next((n for n in self.nodes if n.concept_id == concept_id), None)


# ---------------------------------------------------------------------------
# Learner model
# ---------------------------------------------------------------------------


class SessionTurn(BaseModel):
    concept_id: str
    modality: Modality
    correct: bool | None = None
    notes: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class LearnerModel(BaseModel):
    user_id: str
    domain_id: str
    mastered_concepts: list[str] = Field(default_factory=list)
    struggling_concepts: list[str] = Field(default_factory=list)
    modality_preference: Modality = Modality.READING
    difficulty_level: int = Field(default=1, ge=1, le=5)
    session_history: list[SessionTurn] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Diagnosis + workflow
# ---------------------------------------------------------------------------


class GapEstimate(BaseModel):
    target_concept_id: str
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_difficulty: int = Field(ge=1, le=5)
    prerequisite_gaps: list[str] = Field(default_factory=list)


class WorkflowStep(BaseModel):
    step_number: int
    concept_id: str
    modality: Modality
    objective: str
    pedagogy_principle: str  # e.g. "interleaving", "desirable_difficulty"


class Workflow(BaseModel):
    target_concept_id: str
    modality: Modality
    steps: list[WorkflowStep]
    rationale: str  # why this sequence, why this modality


# ---------------------------------------------------------------------------
# Generated artifacts
# ---------------------------------------------------------------------------


class QuizQuestion(BaseModel):
    question: str
    options: list[str] | None = None  # None for free-response
    correct_answer: str
    explanation: str


class ReadingArtifact(BaseModel):
    type: Literal["reading"] = "reading"
    title: str
    body: str  # markdown
    key_takeaways: list[str]


class InteractiveArtifact(BaseModel):
    type: Literal["interactive"] = "interactive"
    title: str
    intro: str
    questions: list[QuizQuestion]


class SocraticTurn(BaseModel):
    role: Literal["agent", "learner_prompt"]
    text: str


class SocraticArtifact(BaseModel):
    type: Literal["socratic"] = "socratic"
    title: str
    opening: str
    dialogue: list[SocraticTurn]  # the script the agent can run
    target_insight: str


Artifact = ReadingArtifact | InteractiveArtifact | SocraticArtifact


# ---------------------------------------------------------------------------
# Eval judges
# ---------------------------------------------------------------------------


class JudgeResult(BaseModel):
    judge_name: str
    score: float = Field(ge=0.0, le=1.0)
    rationale: str


class EvalCase(BaseModel):
    case_id: str
    domain_id: str
    learner_model: LearnerModel
    expected_target_concept: str
    expected_modality: Modality
    expected_difficulty_band: tuple[int, int]  # (min, max)
    description: str


class EvalResult(BaseModel):
    case_id: str
    workflow: Workflow
    artifact_type: str
    judge_results: list[JudgeResult]

    @property
    def passed(self) -> bool:
        return all(j.score >= 0.6 for j in self.judge_results)
