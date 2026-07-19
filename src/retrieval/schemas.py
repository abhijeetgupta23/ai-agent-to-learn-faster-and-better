"""
Pydantic schemas for the retrieval layer.

These are the public data contracts of the evidence service (see
docs/RAG_ARCHITECTURE.md §"The seam"). They are introduced before any new
retrieval strategy so that ingestion, indexing, benchmarking, and the tutor
integration can all be built against one stable vocabulary.

Versioning fields (`corpus_version`, `parser_version`, `chunker_version`) are
mandatory where they appear: no benchmark result is interpretable unless it is
tied to the exact corpus and processing code that produced its chunks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# The strategies the benchmark harness can select between. "lexical" is the
# existing deterministic term-overlap baseline (src/graph/retriever.py) — kept
# selectable forever as the floor every new strategy must beat. "oracle"
# injects labelled relevant chunks to isolate generation failures from
# retrieval failures.
RetrievalStrategy = Literal["lexical", "bm25", "dense", "hybrid", "hybrid_reranked", "oracle"]


class SourceDocument(BaseModel):
    """One ingested document (Markdown file, web page, PDF, code file)."""

    document_id: str
    title: str
    source_type: Literal["markdown", "pdf", "html", "code"]
    canonical_uri: str
    collection: str
    content_hash: str
    corpus_version: str
    parser_version: str
    fetched_at: datetime | None = None


class Chunk(BaseModel):
    """A retrievable passage of a document, produced by a versioned chunker."""

    chunk_id: str
    document_id: str
    text: str
    heading_path: list[str] = Field(default_factory=list)
    page_number: int | None = None
    token_count: int
    contains_code: bool = False
    contains_table: bool = False
    source_uri: str
    chunker_version: str


class PedagogicalMetadata(BaseModel):
    """Teaching-oriented labels attached to a chunk (filled by later milestones;
    the lexical baseline does not populate these)."""

    concepts: list[str] = Field(default_factory=list)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    content_type: (
        Literal[
            "definition",
            "explanation",
            "example",
            "procedure",
            "comparison",
            "warning",
            "exercise",
            "reference",
        ]
        | None
    ) = None
    suitable_modalities: list[Literal["reading", "interactive", "socratic"]] = Field(
        default_factory=list
    )
    prerequisites: list[str] = Field(default_factory=list)
    misconceptions_addressed: list[str] = Field(default_factory=list)


class RetrievalRequest(BaseModel):
    """A single benchmarkable retrieval query. The teaching context fields are
    optional so the same schema serves both bare benchmark questions and
    learner-state-aware tutoring queries."""

    query: str
    target_concept_id: str | None = None
    objective: str | None = None
    modality: Literal["reading", "interactive", "socratic"] | None = None
    learner_difficulty: int | None = Field(default=None, ge=1, le=5)
    mastered_prerequisites: list[str] = Field(default_factory=list)
    struggling_concepts: list[str] = Field(default_factory=list)
    strategy: RetrievalStrategy
    top_k: int = 5


class RetrievedPassage(BaseModel):
    """One ranked passage plus every score that contributed to its rank, so a
    per-query trace can explain *why* it was retrieved."""

    chunk: Chunk
    rank: int
    sparse_score: float | None = None
    dense_score: float | None = None
    fused_score: float | None = None
    reranker_score: float | None = None
    retrieval_reason: str | None = None


class Citation(BaseModel):
    """A learner-facing pointer from generated content back to its evidence."""

    chunk_id: str
    document_title: str
    source_uri: str
    page_number: int | None = None
    supporting_text: str | None = None


class RetrievalBundle(BaseModel):
    """What `StudyMaterialRetriever.retrieve_for_lesson` returns.

    `grounded=False` is a first-class, traceable outcome — `retrieval_trace`
    must then carry a `reason`. Callers fall back to ungrounded generation
    explicitly; the system never silently pretends a lesson is grounded.

    `source_context` is the exact string to pass to
    `generate_artifact(source_context=...)` (None when not grounded). Carrying
    the assembled context on the bundle is what lets the tutor swap retriever
    implementations without re-deriving prompt text from passages at the call
    site.
    """

    passages: list[RetrievedPassage] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    retrieval_trace: dict = Field(default_factory=dict)
    grounded: bool
    corpus_version: str
    source_context: str | None = None
