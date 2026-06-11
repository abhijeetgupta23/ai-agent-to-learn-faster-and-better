"""
AI-domain demo: extract a learning graph from domains/ai.md, run two sessions
on the same learner (one fresh, one mid-journey), capture full reasoning
traces for both.

Output:
  docs/ai_use_case_trace.json       — the structured trace data
  docs/traces/ai_fresh.md            — call-by-call reasoning trace (novice)
  docs/traces/ai_struggling.md       — call-by-call reasoning trace (struggling)

Run:
  PYTHONPATH=. python scripts/ai_demo.py
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
from src.trace import trace


def log(msg: str) -> None:
    print(f"[ai-demo] {msg}", file=sys.stderr, flush=True)


def run_session(label: str, learner: LearnerModel, graph, trace_dir: Path):
    """Run diagnose → plan → generate with full tracing."""
    with trace(f"AI domain — {label}") as tr:
        gap = diagnose_learner(learner, graph)
        workflow = plan_workflow(gap, learner, graph)
        # Pick the step targeting the gap (typically the third or fourth)
        key_step = next(
            (s for s in workflow.steps if s.concept_id == gap.target_concept_id),
            workflow.steps[len(workflow.steps) // 2],
        )
        concept = graph.node_by_id(key_step.concept_id)
        artifact = generate_artifact(key_step, concept, learner)

    trace_dir.mkdir(parents=True, exist_ok=True)
    tr.save_json(trace_dir / f"ai_{label}.json")
    (trace_dir / f"ai_{label}.md").write_text(tr.render_markdown())
    return {
        "label": label,
        "learner": learner.model_dump(mode="json"),
        "gap": gap.model_dump(mode="json"),
        "workflow": workflow.model_dump(mode="json"),
        "key_step": key_step.model_dump(mode="json"),
        "artifact": artifact.model_dump(mode="json"),
    }


def main() -> int:
    store = MemoryStore()
    out = {"domain": "ai", "sessions": []}

    # 1. Extract the AI graph (cached after first run)
    src = Path("domains/ai.md").read_text()
    log("extracting AI learning graph...")
    t0 = time.perf_counter()
    graph = extract_learning_graph(src, "AI: building with LLMs", store)
    log(f"  {len(graph.nodes)} nodes, {len(graph.edges)} edges "
        f"in {time.perf_counter() - t0:.1f}s")
    out["graph"] = {
        "n_nodes": len(graph.nodes),
        "n_edges": len(graph.edges),
        "node_ids": [n.concept_id for n in graph.nodes],
        "interleave_edges": [
            {"source": e.source, "target": e.target}
            for e in graph.edges if e.relationship_type.value == "interleave_with"
        ],
    }

    trace_dir = Path("docs/traces")

    # 2. Session A — fresh learner (you, opening the project for the first time)
    fresh = LearnerModel(
        user_id="builder",
        domain_id=graph.domain_id,
        mastered_concepts=[],
        struggling_concepts=[],
        modality_preference=Modality.READING,
        difficulty_level=1,
        session_history=[],
    )
    log("session 1: fresh learner (no prior knowledge)")
    out["sessions"].append(run_session("fresh", fresh, graph, trace_dir))

    # 3. Session B — learner who's read tokens/embeddings/attention but is
    # stuck on RAG retrieval quality
    ids = [n.concept_id for n in graph.nodes]
    foundational = [c for c in ids if c in {"tokens", "embeddings", "attention", "transformers"}]
    # Pick a struggling target: prefer RAG / agents / evals if present
    struggling_target = next(
        (c for c in ids if c in {"rag", "retrieval_augmented_generation", "agents", "evals", "tool_use"}),
        ids[-1],
    )
    struggling = LearnerModel(
        user_id="builder",
        domain_id=graph.domain_id,
        mastered_concepts=foundational,
        struggling_concepts=[struggling_target],
        modality_preference=Modality.READING,
        difficulty_level=3,
        session_history=[
            SessionTurn(concept_id=struggling_target, modality=Modality.READING, correct=False),
            SessionTurn(concept_id=struggling_target, modality=Modality.READING, correct=False),
        ],
    )
    log(f"session 2: struggling on {struggling_target} after 2 reading attempts")
    out["sessions"].append(run_session("struggling", struggling, graph, trace_dir))

    print(json.dumps(out, indent=2))
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
