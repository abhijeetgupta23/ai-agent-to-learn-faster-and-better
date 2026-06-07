"""
Source retrieval for grounded generation.

`generate_artifact` historically taught from a concept's short description plus
the model's parametric memory — nothing tied the lesson to the actual source
material, so facts could drift. This module retrieves the passage(s) of the
original source that correspond to a concept, so generation can be *grounded*:
the lesson is built from real source text, not the model's recollection.

Deliberately dependency-free. The graphs here are small (6-15 concepts) and the
sources are short, well-structured Markdown, so a lexical (term-overlap)
retriever over heading-delimited sections is both sufficient and deterministic.
The seam is shaped so an embedding backend can replace `_score` later without
touching call sites (see MemoryStore's note on `find_similar`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.schemas import ConceptNode, LearningGraph

# Small stopword set — enough to stop "the/of/a" from dominating overlap scores.
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the to "
    "with we you they this these those their our your he she them him her his".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2]


@dataclass
class Passage:
    heading: str
    text: str          # heading + body, the chunk fed to the model
    score: float


@dataclass
class Retrieval:
    """What grounded generation receives: the passages plus a flag for whether
    retrieval actually found anything usable."""

    passages: list[Passage]
    grounded: bool

    def as_context(self) -> str:
        return "\n\n".join(p.text for p in self.passages)


def chunk_markdown(source_text: str) -> list[Passage]:
    """
    Split a Markdown document into one chunk per section (heading + body up to
    the next heading of any level). The top-level title is prepended to each
    chunk as light context. Score is 0.0 here; `retrieve` fills it in.
    """
    headings = list(_HEADING_RE.finditer(source_text))
    if not headings:
        # No headings — treat the whole thing as one chunk.
        body = source_text.strip()
        return [Passage(heading="", text=body, score=0.0)] if body else []

    doc_title = ""
    first = headings[0]
    if first.group(1) == "#":
        doc_title = first.group(2).strip()

    chunks: list[Passage] = []
    for i, h in enumerate(headings):
        level, title = h.group(1), h.group(2).strip()
        start = h.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(source_text)
        body = source_text[start:end].strip()
        if level == "#":
            # The document title itself rarely has a standalone body worth teaching.
            if not body:
                continue
        if not body:
            continue
        prefix = f"[{doc_title}] " if doc_title and title != doc_title else ""
        chunks.append(Passage(heading=title, text=f"{prefix}{title}\n{body}", score=0.0))
    return chunks


def _score(chunk: Passage, query_terms: list[str], query_set: frozenset[str]) -> float:
    """
    Term-overlap score with a heading boost. Heading matches weigh heavily
    because in these sources the section heading IS the concept name.
    """
    body_tokens = _tokens(chunk.text)
    if not body_tokens:
        return 0.0
    body_set = set(body_tokens)
    # Coverage: how many distinct query terms appear in the chunk.
    coverage = sum(1 for t in query_set if t in body_set)
    # Frequency: total occurrences (rewards a chunk that's really about the term).
    freq = sum(body_tokens.count(t) for t in query_set)
    heading_tokens = set(_tokens(chunk.heading))
    heading_hits = sum(1 for t in query_set if t in heading_tokens)
    return coverage * 2.0 + freq * 0.5 + heading_hits * 5.0


def retrieve(source_text: str, concept: ConceptNode, *, k: int = 2,
             min_score: float = 1.0) -> Retrieval:
    """
    Return the top-k source passages most relevant to `concept`.

    The query is the concept's name + description + id tokens. If nothing clears
    `min_score`, `grounded` is False and callers should fall back to ungrounded
    generation rather than feeding the model irrelevant text.
    """
    query_text = f"{concept.name} {concept.description} {concept.concept_id.replace('_', ' ')}"
    query_terms = _tokens(query_text)
    query_set = frozenset(query_terms)

    chunks = chunk_markdown(source_text)
    for c in chunks:
        c.score = _score(c, query_terms, query_set)

    ranked = sorted(chunks, key=lambda c: c.score, reverse=True)
    top = [c for c in ranked[:k] if c.score >= min_score]
    return Retrieval(passages=top, grounded=bool(top))


def _source_for_graph(graph: LearningGraph, store) -> str | None:
    """Find the source a graph was extracted from: the store first, then a
    `domains/<domain_id>.md` fallback for graphs saved before sources were kept."""
    if store is not None:
        src = store.get_source(graph.source_hash)
        if src:
            return src
    fallback = Path("domains") / f"{graph.domain_id}.md"
    return fallback.read_text() if fallback.exists() else None


def ground_context(concept: ConceptNode, graph: LearningGraph, store, *, k: int = 2) -> str | None:
    """
    Convenience for call sites: resolve the source for `graph`, retrieve the
    passages for `concept`, and return them as a context string ready to pass
    to `generate_artifact(source_context=...)`. Returns None when no source is
    available or nothing relevant is found, so callers fall back to ungrounded
    generation transparently.
    """
    source = _source_for_graph(graph, store)
    if not source:
        return None
    retrieval = retrieve(source, concept, k=k)
    return retrieval.as_context() if retrieval.grounded else None
