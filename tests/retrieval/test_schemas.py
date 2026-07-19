"""
Contract tests for the retrieval-layer schemas: required fields, bounds, and
JSON round-trips. Offline, no LLM.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.retrieval.schemas import (
    Chunk,
    PedagogicalMetadata,
    RetrievalBundle,
    RetrievalRequest,
    SourceDocument,
)


def _chunk(**overrides) -> Chunk:
    base = dict(
        chunk_id="c1",
        document_id="d1",
        text="Scarcity raises perceived value.",
        token_count=5,
        source_uri="store://sources/d1",
        chunker_version="legacy-markdown-sections-v1",
    )
    base.update(overrides)
    return Chunk(**base)


def test_chunk_round_trips_through_json():
    c = _chunk(heading_path=["Scarcity"], contains_code=False)
    assert Chunk.model_validate_json(c.model_dump_json()) == c


def test_source_document_fetched_at_is_optional():
    doc = SourceDocument(
        document_id="d1",
        title="Persuasion",
        source_type="markdown",
        canonical_uri="domains/persuasion.md",
        collection="repo",
        content_hash="abc123",
        corpus_version="v1",
        parser_version="p1",
    )
    assert doc.fetched_at is None


def test_retrieval_request_accepts_lexical_baseline_strategy():
    req = RetrievalRequest(query="what is scarcity", strategy="lexical")
    assert req.top_k == 5 and req.mastered_prerequisites == []


def test_retrieval_request_rejects_unknown_strategy():
    with pytest.raises(ValidationError):
        RetrievalRequest(query="q", strategy="graph_guided")  # V2, not selectable yet


def test_pedagogical_metadata_difficulty_bounds():
    with pytest.raises(ValidationError):
        PedagogicalMetadata(difficulty=6)


def test_bundle_requires_explicit_grounded_flag():
    with pytest.raises(ValidationError):
        RetrievalBundle(corpus_version="v1")  # grounded must be stated, never implied


def test_ungrounded_bundle_defaults_are_empty():
    b = RetrievalBundle(grounded=False, corpus_version="v1")
    assert b.passages == [] and b.citations == [] and b.source_context is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
