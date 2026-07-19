"""
Stable public interface of the retrieval layer, plus the legacy adapter.

`StudyMaterialRetriever` is the seam the tutor will integrate against
(docs/RAG_ARCHITECTURE.md): the `teach` tool asks for evidence for one lesson;
implementations decide how to find it. New strategies (BM25, dense, hybrid,
graph-guided) implement this protocol and get benchmarked against each other
before any of them touches the agent loop.

`LexicalStudyMaterialRetriever` wraps the existing deterministic lexical path
(src/graph/retriever.py) behind the protocol. It delegates the context string
to the legacy `ground_context()` itself — equivalence by construction, pinned
by tests/retrieval/test_lexical_adapter.py — and adds the structured view
(ranked passages, citations, a retrieval trace) the legacy path never exposed.
Nothing at runtime calls this class yet; the swap happens in a later milestone
once the regression tests exist.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol, runtime_checkable

from src.graph.retriever import Passage, Retrieval, ground_context, retrieve
from src.memory.store import MemoryStore
from src.retrieval.schemas import Chunk, Citation, RetrievalBundle, RetrievedPassage
from src.schemas import ConceptNode, LearnerModel, LearningGraph, Modality

# The heading-delimited chunker in src/graph/retriever.py, as consumed here.
# Bump if chunk_markdown's chunking behaviour ever changes.
CHUNKER_VERSION = "legacy-markdown-sections-v1"

# ground_context()'s defaults, mirrored so the adapter's default call is
# byte-equivalent to the current runtime call site (autonomous.py `teach`).
LEGACY_TOP_K = 2   # target-concept passages (ground_context's k)
_BRIDGE_K = 1      # ground_context always retrieves prerequisite bridges with k=1
_MAX_BRIDGES = 2   # ...and appends at most two of them


@runtime_checkable
class StudyMaterialRetriever(Protocol):
    """What the tutor needs from any retrieval backend: evidence for teaching
    one concept to one learner, with citations and an explicit grounded flag."""

    def retrieve_for_lesson(
        self,
        *,
        target_concept: ConceptNode,
        learner: LearnerModel,
        objective: str,
        modality: Modality,
        graph: LearningGraph,
        top_k: int = 5,
    ) -> RetrievalBundle:
        ...


def _resolve_source(graph: LearningGraph, store: MemoryStore | None) -> tuple[str, str] | None:
    """(source_text, source_uri) for a graph, or None. Mirrors the resolution
    order of the legacy `_source_for_graph`: the store first, then the
    `domains/<domain_id>.md` fallback for graphs saved before sources were kept."""
    if store is not None:
        src = store.get_source(graph.source_hash)
        if src:
            return src, f"store://sources/{graph.source_hash}"
    fallback = Path("domains") / f"{graph.domain_id}.md"
    if fallback.exists():
        return fallback.read_text(), str(fallback)
    return None


class LexicalStudyMaterialRetriever:
    """The existing lexical retriever, presented through the stable interface.

    This is the permanent deterministic baseline: dependency-free, offline,
    reproducible. Every future strategy is benchmarked against it, and
    oracle/no-retrieval comparisons reuse the same bundle shape.
    """

    strategy = "lexical"

    def __init__(self, store: MemoryStore | None = None):
        # `store=None` mirrors the legacy call sites, where a session may run
        # without a MemoryStore and grounding falls back to domains/<id>.md.
        self._store = store

    def retrieve_for_lesson(
        self,
        *,
        target_concept: ConceptNode,
        learner: LearnerModel | None,
        objective: str,
        modality: Modality,
        graph: LearningGraph,
        # Default intentionally LEGACY_TOP_K (2), not the protocol's 5: the
        # adapter's contract is byte-equivalence with today's runtime call.
        top_k: int = LEGACY_TOP_K,
    ) -> RetrievalBundle:
        trace: dict = {
            "strategy": self.strategy,
            "target_concept_id": target_concept.concept_id,
            "requested_top_k": top_k,
            "objective": objective,
            "modality": getattr(modality, "value", modality),
        }

        resolved = _resolve_source(graph, self._store)
        if resolved is None:
            trace["reason"] = "no_source_available"
            return RetrievalBundle(
                grounded=False, corpus_version=graph.source_hash, retrieval_trace=trace
            )
        source_text, source_uri = resolved
        trace["source_uri"] = source_uri

        # The authoritative context string comes from the legacy function
        # itself — the adapter cannot drift from ground_context() because it IS
        # ground_context(). The structured view below re-runs the same
        # deterministic retrieval to expose what the string was built from.
        source_context = ground_context(
            target_concept, graph, self._store, k=top_k, learner=learner
        )
        if source_context is None:
            trace["reason"] = "no_passage_above_threshold"
            return RetrievalBundle(
                grounded=False, corpus_version=graph.source_hash, retrieval_trace=trace
            )

        target: Retrieval = retrieve(source_text, target_concept, k=top_k)
        passages: list[RetrievedPassage] = []
        for p in target.passages:
            passages.append(
                self._as_retrieved(
                    p, graph, source_uri, rank=len(passages) + 1, reason="target_concept"
                )
            )

        # Mirror ground_context's bridge selection: up to two *mastered*
        # prerequisites, in the concept's prerequisite order, one passage each.
        bridge_trace = []
        if learner is not None:
            mastered = set(learner.mastered_concepts)
            for pid in [p for p in target_concept.prerequisites if p in mastered][:_MAX_BRIDGES]:
                prereq = graph.node_by_id(pid)
                if prereq is None:
                    continue
                bridge = retrieve(source_text, prereq, k=_BRIDGE_K)
                if not bridge.grounded:
                    continue
                for p in bridge.passages:
                    passages.append(
                        self._as_retrieved(
                            p, graph, source_uri,
                            rank=len(passages) + 1,
                            reason=f"prerequisite_bridge:{pid}",
                        )
                    )
                    bridge_trace.append({"concept_id": pid, "heading": p.heading, "score": p.score})

        trace["target_passages"] = [
            {"heading": p.heading, "score": p.score} for p in target.passages
        ]
        trace["bridge_passages"] = bridge_trace

        citations = [
            Citation(
                chunk_id=rp.chunk.chunk_id,
                document_title=graph.domain_title,
                source_uri=source_uri,
            )
            for rp in passages
        ]
        return RetrievalBundle(
            passages=passages,
            citations=citations,
            retrieval_trace=trace,
            grounded=True,
            corpus_version=graph.source_hash,
            source_context=source_context,
        )

    @staticmethod
    def _as_retrieved(
        p: Passage, graph: LearningGraph, source_uri: str, *, rank: int, reason: str
    ) -> RetrievedPassage:
        chunk_id = hashlib.sha256(
            f"{graph.source_hash}:{p.heading}:{p.text}".encode()
        ).hexdigest()[:16]
        chunk = Chunk(
            chunk_id=chunk_id,
            document_id=graph.source_hash,
            text=p.text,
            heading_path=[p.heading] if p.heading else [],
            # Whitespace tokens — a versioned tokenizer arrives with ingestion.
            token_count=len(p.text.split()),
            contains_code="```" in p.text,
            source_uri=source_uri,
            chunker_version=CHUNKER_VERSION,
        )
        # The lexical term-overlap score is a sparse (term-based) signal, so it
        # rides in sparse_score; dense/fused/reranker stay None for this strategy.
        return RetrievedPassage(
            chunk=chunk, rank=rank, sparse_score=p.score, retrieval_reason=reason
        )
