"""
Pydantic schemas for the adaptive-learning-agent.

Every tool call returns one of these. The agent loop fails fast on validation
errors rather than swallowing malformed LLM output.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


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


# ---------------------------------------------------------------------------
# Learn Faster v1 (§7): records and course format. Added next to the old
# models; nothing above is changed.
# ---------------------------------------------------------------------------

PriorLevel = Literal["none", "seen", "used"]
TutorMove = Literal[
    "ask", "walkthrough_check", "set_task", "explain", "example", "hint",
    "fix", "note", "built_alone", "show_progress", "confirm_mastery",
]
HelpKind = Literal["explain", "example", "hint", "fix"]
WalkthroughKind = Literal["explain", "change", "fix"]
ContentType = Literal["code"]  # more subjects later
GateName = Literal["try_first_gate", "built_alone_gate", "progress_gate", "mastery_gate"]

Id = Field(min_length=1)

# A timestamp that must carry a timezone, always stored in UTC.
UtcTime = Annotated[AwareDatetime, AfterValidator(lambda t: t.astimezone(timezone.utc))]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Learner(_Strict):
    id: str = Id
    prior_knowledge: dict[str, PriorLevel] = Field(default_factory=dict)  # skill_id -> level
    current_course: str | None = None
    current_milestone: str | None = None


class Skill(_Strict):
    id: str = Id
    course: str = Id
    needs: list[str] = Field(default_factory=list)
    must_know: bool = False
    first_learned_session: str | None = None  # None until first learned


class TaskBrief(_Strict):
    why: str = Id
    done_looks_like: str = Id
    you_start_with: str = Id


class Task(_Strict):
    id: str = Id
    milestone: str = Id
    skill_ids: list[str] = Field(min_length=1)
    brief: TaskBrief


class Submission(_Strict):
    id: str = Id
    task_id: str = Id
    learner_id: str = Id
    content: str
    content_type: ContentType = "code"
    ts: UtcTime


class WalkthroughCheck(_Strict):
    submission_id: str = Id
    kind: WalkthroughKind
    passed: bool
    ts: UtcTime


class TestFailure(_Strict):
    __test__ = False  # not a pytest class

    test: str = Id
    message: str


class RedFlag(_Strict):
    rule_id: str = Id
    line: int | None = None
    message: str = ""


class TestResult(_Strict):
    __test__ = False  # not a pytest class

    submission_id: str = Id
    passed: int = Field(ge=0)
    total: int = Field(ge=0)
    failures: list[TestFailure] = Field(default_factory=list)
    red_flags: list[RedFlag] = Field(default_factory=list)

    @model_validator(mode="after")
    def _passed_not_over_total(self) -> "TestResult":
        if self.passed > self.total:
            raise ValueError("passed cannot be greater than total")
        return self


class JudgeReview(_Strict):
    submission_id: str = Id
    method_ok: bool
    notes: str
    model: str


class TutorMoveLog(_Strict):
    session_id: str = Id
    move: TutorMove
    skill_id: str | None = None
    gate: GateName | Literal[""] | None = None  # "" or None = no gate involved
    allowed: bool
    reason: str = ""
    ts: UtcTime
    tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)


class TutorHelpLog(_Strict):
    session_id: str = Id
    task_id: str = Id
    kind: HelpKind
    ts: UtcTime


class SkillUseLog(_Strict):
    learner_id: str = Id
    skill_id: str = Id
    session_id: str = Id
    gap_days: float | None = Field(default=None, ge=0)  # None = first use
    help_used: bool
    unaided: bool
    ts: UtcTime


class MasteryLog(_Strict):
    learner_id: str = Id
    skill_id: str = Id
    confirmed: bool
    ts: UtcTime


class RedFlagRule(_Strict):
    id: str = Id
    description: str
    pattern: str  # regex; data only, nothing runs it yet

    @field_validator("pattern")
    @classmethod
    def _pattern_compiles(cls, v: str) -> str:
        import re

        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"pattern is not a valid regex: {e}") from e
        return v


class JudgeRubric(_Strict):
    criteria: list[str] = Field(min_length=1)


class Milestone(_Strict):
    id: str = Id
    order: int = Field(ge=1)
    title: str
    task: Task
    tests: list[str] = Field(min_length=1)  # paths relative to the course folder
    reference_solution: str = Id  # path relative to the course folder


class Course(_Strict):
    id: str = Id
    title: str
    subject: str
    skills: list[Skill] = Field(min_length=1)
    milestones: list[Milestone] = Field(min_length=1)
    red_flag_rules: list[RedFlagRule] = Field(default_factory=list)
    judge_rubric: JudgeRubric
    walkthrough_questions: dict[WalkthroughKind, list[str]]

    @model_validator(mode="after")
    def _cross_checks(self) -> "Course":
        ids = [s.id for s in self.skills]
        if len(set(ids)) != len(ids):
            raise ValueError("skill ids must be unique")
        known = set(ids)
        for s in self.skills:
            for n in s.needs:
                if n not in known:
                    raise ValueError(f"skill {s.id!r} needs unknown skill {n!r}")
        for m in self.milestones:
            if m.task.milestone != m.id:
                raise ValueError(f"task.milestone {m.task.milestone!r} != milestone id {m.id!r}")
            for sid in m.task.skill_ids:
                if sid not in known:
                    raise ValueError(f"milestone {m.id!r} task names unknown skill {sid!r}")
        if sorted(m.order for m in self.milestones) != list(range(1, len(self.milestones) + 1)):
            raise ValueError("milestone orders must be 1..n with no gaps")
        missing = {"explain", "change", "fix"} - set(self.walkthrough_questions)
        if missing:
            raise ValueError(f"walkthrough_questions missing kinds: {sorted(missing)}")
        return self
