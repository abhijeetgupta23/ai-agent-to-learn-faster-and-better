"""
Naval seven-disciplines demo.

Extracts learning graphs for two of the seven Naval domains, then runs the
agent on the same learner across both domains to show:

  1. The same agent producing different curricula per domain (graphs differ in
     prerequisite depth and concept density).
  2. Modality routing varying by domain (psychology → Socratic for a known
     misconception; persuasion → interactive for an applied skill).
  3. Difficulty calibration adapting per learner state, per domain.

Run:
    python scripts/naval_demo.py > docs/naval_use_case_trace.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from src.graph.extractor import extract_learning_graph
from src.memory.store import MemoryStore
from src.schemas import LearnerModel, Modality, SessionTurn
from src.tools import diagnose_learner, generate_artifact, plan_workflow

DOMAINS_TO_EXTRACT = ["psychology", "persuasion"]
DOMAIN_TITLES = {
    "psychology": "Psychology",
    "persuasion": "Persuasion",
    "microeconomics": "Microeconomics",
    "game_theory": "Game Theory",
    "ethics": "Ethics",
    "mathematics": "Mathematics",
    "computers": "Computers",
}


def log(msg: str) -> None:
    print(f"[demo] {msg}", file=sys.stderr, flush=True)


def main() -> int:
    store = MemoryStore()
    output = {"domains": {}, "sessions": []}

    # 1. Extract graphs for the two domains we'll trace.
    for slug in DOMAINS_TO_EXTRACT:
        path = Path("domains") / f"{slug}.md"
        if not path.exists():
            log(f"missing {path}")
            return 1
        log(f"extracting graph: {slug}")
        t0 = time.perf_counter()
        graph = extract_learning_graph(path.read_text(), DOMAIN_TITLES[slug], store)
        log(f"  {slug}: {len(graph.nodes)} nodes, {len(graph.edges)} edges "
            f"({(time.perf_counter() - t0):.1f}s)")
        output["domains"][slug] = {
            "n_nodes": len(graph.nodes),
            "n_edges": len(graph.edges),
            "node_ids": [n.concept_id for n in graph.nodes],
            "interleave_edges": [
                {"source": e.source, "target": e.target}
                for e in graph.edges
                if e.relationship_type.value == "interleave_with"
            ],
        }

    # 2. Session A — psychology. Learner has dabbled, marks one bias as struggling.
    psych_graph = next(
        store.get_graph_by_source_hash(g["source_hash"])
        for g in store.list_graphs()
        if g["domain_id"] == "psychology"
    )
    psych_ids = [n.concept_id for n in psych_graph.nodes]

    # Pick a foundational concept for "mastered" and a downstream one for "struggling".
    foundational = next(
        (n for n in psych_graph.nodes if not n.prerequisites and n.difficulty <= 2),
        psych_graph.nodes[0],
    )
    downstream = next(
        (n for n in psych_graph.nodes if n.prerequisites and n.difficulty >= 3),
        psych_graph.nodes[-1],
    )
    log(f"psych learner: mastered={foundational.concept_id}, struggling={downstream.concept_id}")

    psych_learner = LearnerModel(
        user_id="alice",
        domain_id=psych_graph.domain_id,
        mastered_concepts=[foundational.concept_id],
        struggling_concepts=[downstream.concept_id],
        modality_preference=Modality.READING,
        difficulty_level=3,
        session_history=[
            SessionTurn(concept_id=downstream.concept_id, modality=Modality.READING, correct=False),
            SessionTurn(concept_id=downstream.concept_id, modality=Modality.READING, correct=False),
        ],
    )

    log("psych: diagnose → plan → generate")
    psych_gap = diagnose_learner(psych_learner, psych_graph)
    psych_workflow = plan_workflow(psych_gap, psych_learner, psych_graph)
    key_step = next(
        (s for s in psych_workflow.steps if s.concept_id == psych_gap.target_concept_id),
        psych_workflow.steps[len(psych_workflow.steps) // 2],
    )
    key_concept = psych_graph.node_by_id(key_step.concept_id)
    psych_artifact = generate_artifact(key_step, key_concept, psych_learner)
    output["sessions"].append({
        "domain": "psychology",
        "learner": psych_learner.model_dump(mode="json"),
        "gap": psych_gap.model_dump(mode="json"),
        "workflow": psych_workflow.model_dump(mode="json"),
        "key_step_number": key_step.step_number,
        "key_artifact": psych_artifact.model_dump(mode="json"),
    })

    # 3. Session B — persuasion. Same learner, fresh in this domain.
    pers_graph = next(
        store.get_graph_by_source_hash(g["source_hash"])
        for g in store.list_graphs()
        if g["domain_id"] == "persuasion"
    )

    pers_learner = LearnerModel(
        user_id="alice",
        domain_id=pers_graph.domain_id,
        mastered_concepts=[],
        struggling_concepts=[],
        modality_preference=Modality.READING,
        difficulty_level=1,
        session_history=[],
    )

    log("persuasion: diagnose → plan → generate")
    pers_gap = diagnose_learner(pers_learner, pers_graph)
    pers_workflow = plan_workflow(pers_gap, pers_learner, pers_graph)
    pers_step = pers_workflow.steps[0]
    pers_concept = pers_graph.node_by_id(pers_step.concept_id)
    pers_artifact = generate_artifact(pers_step, pers_concept, pers_learner)
    output["sessions"].append({
        "domain": "persuasion",
        "learner": pers_learner.model_dump(mode="json"),
        "gap": pers_gap.model_dump(mode="json"),
        "workflow": pers_workflow.model_dump(mode="json"),
        "key_step_number": pers_step.step_number,
        "key_artifact": pers_artifact.model_dump(mode="json"),
    })

    print(json.dumps(output, indent=2))
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
