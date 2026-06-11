"""
Grounded-generation demo.

Shows the difference retrieval makes: for one concept, it prints
  1. the source passage the retriever pulled,
  2. an UNGROUNDED lesson (generated from the concept description + model memory),
  3. a GROUNDED lesson (generated from the retrieved source passage).

The point: the grounded lesson's domain-specific claims trace back to the
source, while the ungrounded one is whatever the model happened to recall.

Run:
    python scripts/grounded_demo.py                 # default: persuasion / scarcity
    python scripts/grounded_demo.py game_theory nash_equilibrium
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.graph.extractor import extract_learning_graph
from src.graph.retriever import retrieve
from src.memory.store import MemoryStore
from src.schemas import LearnerModel, Modality, WorkflowStep
from src.tools import generate_artifact


def _print_reading(label: str, art) -> None:
    print(f"\n{'='*70}\n{label}\n{'='*70}")
    print(f"# {art.title}\n")
    print(art.body)
    print("\nKEY TAKEAWAYS:")
    for t in art.key_takeaways:
        print("  -", t)


def main() -> int:
    domain = sys.argv[1] if len(sys.argv) > 1 else "persuasion"
    want_concept = sys.argv[2] if len(sys.argv) > 2 else "scarcity"

    store = MemoryStore()
    path = Path("domains") / f"{domain}.md"
    if not path.exists():
        print(f"no domain file at {path}", file=sys.stderr)
        return 1

    print(f"[demo] extracting/loading graph for {domain} ...", file=sys.stderr)
    graph = extract_learning_graph(path.read_text(), domain.replace("_", " "), store)

    concept = graph.node_by_id(want_concept) or next(
        (n for n in graph.nodes if want_concept in n.concept_id), graph.nodes[-1]
    )
    print(f"[demo] concept: {concept.concept_id} — {concept.name}", file=sys.stderr)

    # --- 1. retrieval ---
    source = store.get_source(graph.source_hash) or path.read_text()
    ret = retrieve(source, concept)
    print(f"\n{'#'*70}\n# RETRIEVED SOURCE PASSAGE(S)  (grounded={ret.grounded})\n{'#'*70}")
    for p in ret.passages:
        print(f"\n[score {p.score:.1f}] heading: {p.heading!r}\n{p.text}")

    step = WorkflowStep(
        step_number=1,
        concept_id=concept.concept_id,
        modality=Modality.READING,
        objective=f"Introduce {concept.name} clearly for a learner new to it.",
        pedagogy_principle="elaboration",
    )
    learner = LearnerModel(user_id="demo", domain_id=graph.domain_id, difficulty_level=2)

    # --- 2. ungrounded ---
    print("\n[demo] generating UNGROUNDED ...", file=sys.stderr)
    ungrounded = generate_artifact(step, concept, learner, source_context=None)
    _print_reading("UNGROUNDED  (from concept description + model memory)", ungrounded)

    # --- 3. grounded ---
    print("\n[demo] generating GROUNDED ...", file=sys.stderr)
    grounded = generate_artifact(step, concept, learner, source_context=ret.as_context())
    _print_reading("GROUNDED  (from retrieved source passage)", grounded)

    return 0


if __name__ == "__main__":
    sys.exit(main())
