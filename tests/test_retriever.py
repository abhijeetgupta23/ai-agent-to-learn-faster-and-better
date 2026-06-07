"""
Pure (no-LLM) tests for the grounded-generation retriever.

The retriever is deterministic and dependency-free, so it can be tested fast and
offline — unlike the generation/judge calls. Run directly (`python
tests/test_retriever.py`) or via pytest.
"""

from __future__ import annotations

from src.graph.retriever import chunk_markdown, retrieve
from src.schemas import ConceptNode

SOURCE = """\
# Persuasion

## Reciprocity

People feel obligated to return favors. Free samples and unsolicited gifts
trigger a reciprocity reflex.

## Scarcity in persuasion

People assign higher value to things they perceive as rare or disappearing.
"Only 3 left in stock" and the velvet rope exploit this. Built on loss aversion.

## Authority

People defer to perceived authority. Titles, uniforms, and credentials matter.
"""


def _concept(cid: str, name: str, desc: str = "") -> ConceptNode:
    return ConceptNode(concept_id=cid, name=name, description=desc, difficulty=2)


def test_chunks_one_per_section_excluding_bare_title():
    chunks = chunk_markdown(SOURCE)
    headings = [c.heading for c in chunks]
    assert headings == ["Reciprocity", "Scarcity in persuasion", "Authority"]


def test_retrieval_routes_concept_to_its_section():
    for cid, name in [("scarcity", "Scarcity"), ("authority", "Authority"),
                      ("reciprocity", "Reciprocity")]:
        r = retrieve(SOURCE, _concept(cid, name), k=1)
        assert r.grounded
        assert name.split()[0].lower() in r.passages[0].heading.lower()


def test_grounded_passage_carries_source_specifics():
    r = retrieve(SOURCE, _concept("scarcity", "Scarcity"), k=1)
    # The distinctive source detail must be in the retrieved context.
    assert "velvet rope" in r.as_context()


def test_no_relevant_section_is_not_grounded():
    # A concept with no lexical overlap should fail the min_score gate, so the
    # caller falls back to ungrounded rather than feeding irrelevant text.
    r = retrieve(SOURCE, _concept("quantum_entanglement", "Quantum Entanglement",
                                  "spooky action at a distance"), k=1)
    assert not r.grounded


def test_empty_source_is_safe():
    r = retrieve("", _concept("scarcity", "Scarcity"))
    assert not r.grounded
    assert r.as_context() == ""


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
