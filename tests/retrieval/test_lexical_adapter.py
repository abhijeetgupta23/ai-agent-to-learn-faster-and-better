"""
Regression tests: the LexicalStudyMaterialRetriever adapter is behaviour-
equivalent to the legacy `ground_context()` path it wraps.

The contract under test — for every scenario the current runtime can hit,
`bundle.source_context` must be byte-identical to what `ground_context()`
returns today, and `grounded` must mirror its None/str outcome. These tests
are the safety net for the later milestone that swaps the tutor's internals
over to the StudyMaterialRetriever interface.

Deterministic and offline (no LLM, no API key), like tests/test_retriever.py.
"""

from __future__ import annotations

import pytest

from src.graph.retriever import ground_context
from src.memory.store import MemoryStore
from src.retrieval.service import LexicalStudyMaterialRetriever, StudyMaterialRetriever
from src.schemas import ConceptNode, LearnerModel, LearningGraph, Modality

SOURCE = """\
# Persuasion

## Reciprocity

People feel obligated to return favors. Free samples and unsolicited gifts
trigger a reciprocity reflex.

## Scarcity

People assign higher value to things they perceive as rare or disappearing.
"Only 3 left in stock" and the velvet rope exploit this. Built on loss aversion.

## Authority

People defer to perceived authority. Titles, uniforms, and credentials matter.

## Social proof

When uncertain, people copy the crowd. Laugh tracks and testimonials work by
manufacturing agreement signals at scale.
"""

SOURCE_HASH = "cafebabe00000001"
# Deliberately NOT a real file in this repo's domains/ — keeps the
# domains/<domain_id>.md fallback inert unless a test opts in via chdir.
DOMAIN_ID = "test_persuasion"


def _node(cid: str, name: str, desc: str = "", prereqs: tuple[str, ...] = ()) -> ConceptNode:
    return ConceptNode(
        concept_id=cid, name=name, description=desc, difficulty=2, prerequisites=list(prereqs)
    )


GRAPH = LearningGraph(
    domain_id=DOMAIN_ID,
    domain_title="Persuasion",
    source_hash=SOURCE_HASH,
    nodes=[
        _node("reciprocity", "Reciprocity"),
        _node("scarcity", "Scarcity"),
        _node("authority", "Authority"),
        _node(
            "social_proof",
            "Social proof",
            "copying the crowd under uncertainty",
            prereqs=("reciprocity", "authority", "scarcity"),
        ),
        # No lexical overlap with SOURCE at all -> never grounds.
        _node("quantum_flux", "Quantum Flux", "entangled qubits teleportation"),
        # Prerequisite id that is not a node in the graph -> must be skipped.
        _node("ghost_prereq_target", "Authority", prereqs=("ghost_concept", "scarcity")),
        # Mastered prerequisite whose concept has no matching section -> skipped.
        _node("unmatched_prereq_target", "Scarcity", prereqs=("quantum_flux", "reciprocity")),
        # Query terms ("people") hit three sections -> exercises top_k > 2.
        _node("compliance", "Compliance", "why people comply with requests"),
    ],
    edges=[],
)


def _learner(mastered: tuple[str, ...] = ()) -> LearnerModel:
    return LearnerModel(user_id="u1", domain_id=DOMAIN_ID, mastered_concepts=list(mastered))


@pytest.fixture()
def store(tmp_path) -> MemoryStore:
    s = MemoryStore(root=str(tmp_path / "store"))
    s.save_source(SOURCE_HASH, SOURCE)
    return s


def _both(store, concept_id: str, learner: LearnerModel | None, top_k: int | None = None):
    """Run the adapter and the legacy function with mirrored arguments."""
    concept = GRAPH.node_by_id(concept_id)
    assert concept is not None
    adapter = LexicalStudyMaterialRetriever(store)
    kw = {} if top_k is None else {"top_k": top_k}
    bundle = adapter.retrieve_for_lesson(
        target_concept=concept,
        learner=learner,
        objective="cover the concept",
        modality=Modality.READING,
        graph=GRAPH,
        **kw,
    )
    legacy_kw = {} if top_k is None else {"k": top_k}
    legacy = ground_context(concept, GRAPH, store, learner=learner, **legacy_kw)
    return bundle, legacy


def _bridge_reasons(bundle) -> list[str]:
    return [
        p.retrieval_reason
        for p in bundle.passages
        if (p.retrieval_reason or "").startswith("prerequisite_bridge:")
    ]


# --- source_context equivalence across the legacy behaviour matrix ----------


def test_equivalent_without_learner(store):
    bundle, legacy = _both(store, "scarcity", learner=None)
    assert legacy is not None
    assert bundle.grounded
    assert bundle.source_context == legacy


def test_equivalent_with_two_bridges_capped_in_prerequisite_order(store):
    # All three prerequisites mastered -> ground_context bridges only the
    # first two in prerequisite order (reciprocity, authority).
    bundle, legacy = _both(
        store, "social_proof", _learner(("scarcity", "authority", "reciprocity"))
    )
    assert bundle.source_context == legacy
    assert legacy.count("[MASTERED PREREQUISITE") == 2
    assert _bridge_reasons(bundle) == [
        "prerequisite_bridge:reciprocity",
        "prerequisite_bridge:authority",
    ]


def test_equivalent_with_subset_of_mastered_prereqs(store):
    bundle, legacy = _both(store, "social_proof", _learner(("authority", "scarcity")))
    assert bundle.source_context == legacy
    assert _bridge_reasons(bundle) == [
        "prerequisite_bridge:authority",
        "prerequisite_bridge:scarcity",
    ]


def test_equivalent_with_no_mastered_prereqs(store):
    bundle, legacy = _both(store, "social_proof", _learner())
    assert bundle.source_context == legacy
    assert "[MASTERED PREREQUISITE" not in legacy
    assert _bridge_reasons(bundle) == []


def test_ghost_prerequisite_id_is_skipped(store):
    # "ghost_concept" is mastered but not a node in the graph.
    bundle, legacy = _both(
        store, "ghost_prereq_target", _learner(("ghost_concept", "scarcity"))
    )
    assert bundle.source_context == legacy
    assert _bridge_reasons(bundle) == ["prerequisite_bridge:scarcity"]


def test_unmatchable_bridge_section_is_skipped(store):
    # "quantum_flux" is mastered and IS a node, but retrieves nothing.
    bundle, legacy = _both(
        store, "unmatched_prereq_target", _learner(("quantum_flux", "reciprocity"))
    )
    assert bundle.source_context == legacy
    assert _bridge_reasons(bundle) == ["prerequisite_bridge:reciprocity"]


def test_top_k_flows_through_to_target_retrieval(store):
    for top_k in (1, 3):
        bundle, legacy = _both(store, "compliance", learner=None, top_k=top_k)
        assert bundle.source_context == legacy
        targets = [p for p in bundle.passages if p.retrieval_reason == "target_concept"]
        assert len(targets) == top_k  # "people" matches 3+ sections


# --- explicit, traceable degraded modes -------------------------------------


def test_ungrounded_concept_reports_reason(store):
    bundle, legacy = _both(store, "quantum_flux", learner=None)
    assert legacy is None
    assert not bundle.grounded
    assert bundle.source_context is None
    assert bundle.passages == [] and bundle.citations == []
    assert bundle.retrieval_trace["reason"] == "no_passage_above_threshold"


def test_missing_source_reports_reason(tmp_path, monkeypatch):
    # Empty store and no domains/<id>.md in CWD -> no source anywhere.
    monkeypatch.chdir(tmp_path)
    empty_store = MemoryStore(root=str(tmp_path / "store"))
    bundle, legacy = _both(empty_store, "scarcity", learner=None)
    assert legacy is None
    assert not bundle.grounded
    assert bundle.source_context is None
    assert bundle.retrieval_trace["reason"] == "no_source_available"


def test_domains_fallback_matches_legacy(tmp_path, monkeypatch):
    # Graphs saved before sources were kept fall back to domains/<id>.md.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "domains").mkdir()
    (tmp_path / "domains" / f"{DOMAIN_ID}.md").write_text(SOURCE)
    bundle, legacy = _both(None, "scarcity", learner=None)
    assert legacy is not None
    assert bundle.grounded
    assert bundle.source_context == legacy
    assert bundle.retrieval_trace["source_uri"].endswith(f"{DOMAIN_ID}.md")


# --- the structured view the legacy path never exposed ----------------------


def test_adapter_satisfies_protocol(store):
    assert isinstance(LexicalStudyMaterialRetriever(store), StudyMaterialRetriever)


def test_structured_view_is_consistent_with_context_string(store):
    bundle, _ = _both(store, "social_proof", _learner(("reciprocity", "authority")))

    # Every passage's chunk text is verbatim inside the assembled context.
    assert bundle.passages
    for rp in bundle.passages:
        assert rp.chunk.text in bundle.source_context

    # Bridge labels in the string correspond 1:1 to bridge passages.
    assert bundle.source_context.count("[MASTERED PREREQUISITE") == len(_bridge_reasons(bundle))

    # Ranks are sequential from 1; lexical score rides in sparse_score only.
    assert [p.rank for p in bundle.passages] == list(range(1, len(bundle.passages) + 1))
    for rp in bundle.passages:
        assert rp.sparse_score is not None and rp.sparse_score > 0
        assert rp.dense_score is None and rp.fused_score is None and rp.reranker_score is None

    # Citations mirror passages; provenance points at the stored source.
    assert [c.chunk_id for c in bundle.citations] == [p.chunk.chunk_id for p in bundle.passages]
    for c in bundle.citations:
        assert c.document_title == "Persuasion"
        assert c.source_uri == f"store://sources/{SOURCE_HASH}"

    # Version pins: the graph's source hash is the corpus version today.
    assert bundle.corpus_version == SOURCE_HASH
    for rp in bundle.passages:
        assert rp.chunk.document_id == SOURCE_HASH
        assert rp.chunk.chunker_version
        assert rp.chunk.token_count > 0

    # Trace explains the query and the candidates.
    trace = bundle.retrieval_trace
    assert trace["strategy"] == "lexical"
    assert trace["target_concept_id"] == "social_proof"
    assert trace["modality"] == "reading"
    assert trace["target_passages"] and trace["bridge_passages"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
