"""
Extract a learning graph from arbitrary source material.

The LLM is asked to produce nodes + edges with pedagogy metadata grounded in
named learning-science principles. We cite the principles in the prompt so the
metadata is not invented from whole cloth.
"""

from __future__ import annotations

from src.llm import complete_json
from src.memory.store import MemoryStore, hash_source
from src.schemas import LearningGraph

EXTRACTOR_SYSTEM = """\
You are a curriculum designer trained in cognitive science. Given source
material on a domain, extract a learning graph: the atomic concepts a learner
must master, with prerequisite relationships and pedagogy metadata.

Ground every metadata choice in a NAMED learning-science principle:

  - SPACED REPETITION (Ebbinghaus 1885, Cepeda et al. 2008): foundational facts
    with low conceptual depth benefit from spaced review. Set
    spaced_repetition_interval_days for these (typical: 1, 3, 7, 14).
  - INTERLEAVING (Rohrer & Taylor 2007): when two concepts are commonly confused
    or share surface features but differ structurally, mark an edge with
    relationship_type='interleave_with' and pedagogy_metadata.interleave=true.
  - DESIRABLE DIFFICULTY (Bjork & Bjork 2011): for concepts where retrieval
    practice helps more than rereading, set
    pedagogy_metadata.desirable_difficulty=true on the incoming prerequisite
    edge.
  - COGNITIVE LOAD (Sweller 1988): rate difficulty (1=trivial, 5=expert) by
    intrinsic cognitive load. Concepts that require holding multiple sub-ideas
    simultaneously rate higher.

Modality hints:
  - 'reading' for conceptual/expository material
  - 'interactive' for procedural/problem-solving concepts (quiz, scenarios)
  - 'socratic' for concepts where misconceptions are common and dialogue surfaces them

Aim for 6-15 concepts. Use snake_case for concept_ids. Every prerequisite in a
node's prerequisites list MUST appear as another node's concept_id.
"""


def extract_learning_graph(
    source_text: str,
    domain_title: str,
    store: MemoryStore | None = None,
    *,
    force_regenerate: bool = False,
) -> LearningGraph:
    """
    Parse source material into a LearningGraph. Cache by source hash.
    """
    source_hash = hash_source(source_text + domain_title)
    store = store or MemoryStore()

    if not force_regenerate:
        cached = store.get_graph_by_source_hash(source_hash)
        if cached is not None:
            return cached

    # Truncate enormous sources — the model gets the gist; learners interact
    # with the graph, not the raw text.
    excerpt = source_text[:30_000]
    user = (
        f"Domain title: {domain_title}\n\n"
        f"Source material:\n---\n{excerpt}\n---\n\n"
        "Extract the learning graph. The domain_id should be a snake_case slug "
        f"derived from the title. Use source_hash='{source_hash}'."
    )

    graph = complete_json(EXTRACTOR_SYSTEM, user, LearningGraph, max_tokens=12000)
    # Force the hash to match what we computed (the LLM may hallucinate it).
    graph.source_hash = source_hash
    graph.domain_title = domain_title

    _validate_graph(graph)
    store.save_graph(graph)
    return graph


def _validate_graph(graph: LearningGraph) -> None:
    """Sanity-check that prerequisites and edges reference real concepts."""
    node_ids = {n.concept_id for n in graph.nodes}
    for node in graph.nodes:
        for pre in node.prerequisites:
            if pre not in node_ids:
                raise ValueError(
                    f"Node '{node.concept_id}' lists prerequisite '{pre}' "
                    f"which is not a concept in the graph."
                )
    for edge in graph.edges:
        if edge.source not in node_ids or edge.target not in node_ids:
            raise ValueError(
                f"Edge {edge.source}->{edge.target} references unknown concept."
            )
