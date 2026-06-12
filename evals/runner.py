"""
Eval harness runner.

Loads golden cases, runs the agent's diagnose+plan+generate path against each,
scores with the three judges, and emits a results table.

The harness intentionally exercises the agent's tools directly (not via the
SSE endpoint) so it can run from CI without spinning up a server. A separate
end-to-end script could hit the live endpoint; the judges would be the same.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evals.judges import (
    judge_adaptive_progression,
    judge_gap_to_pedagogy,
    judge_modality_fit,
)
from src.graph.extractor import extract_learning_graph
from src.memory.store import MemoryStore
from src.schemas import EvalCase, EvalResult, LearningGraph, WorkflowStep
from src.tools import diagnose_learner, generate_artifact, plan_workflow
from src.trace import trace

GOLDEN_DIR = Path(__file__).parent / "golden"
DOMAINS_DIR = Path(__file__).parent.parent / "domains"


def load_cases() -> list[EvalCase]:
    cases = []
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        cases.append(EvalCase.model_validate_json(path.read_text()))
    return cases


def _load_graph(domain_id: str, store: MemoryStore) -> LearningGraph:
    """
    Eval graphs are checked into evals/golden/graphs/ — deterministic, so we
    don't pay LLM cost (or non-determinism) for graph extraction during evals.
    """
    graph_path = GOLDEN_DIR / "graphs" / f"{domain_id}.json"
    if graph_path.exists():
        graph = LearningGraph.model_validate_json(graph_path.read_text())
        store.save_graph(graph)
        return graph

    # Fall back to extracting from domains/<id>.md
    domain_path = DOMAINS_DIR / f"{domain_id}.md"
    if not domain_path.exists():
        raise FileNotFoundError(
            f"No checked-in graph for domain '{domain_id}', and no source at "
            f"{domain_path}. Add evals/golden/graphs/{domain_id}.json or "
            f"domains/{domain_id}.md."
        )
    return extract_learning_graph(
        domain_path.read_text(), domain_title=domain_id.replace("_", " "), store=store
    )


def run_case(case: EvalCase, store: MemoryStore, trace_dir: Path | None = None) -> EvalResult:
    graph = _load_graph(case.domain_id, store)

    with trace(case.case_id) as tracer:
        gap = diagnose_learner(case.learner_model, graph)
        workflow = plan_workflow(gap, case.learner_model, graph)

        # Generate the first step's artifact — enough to record the artifact type
        # (the modality is what we score).
        first_step: WorkflowStep = workflow.steps[0]
        concept = graph.node_by_id(first_step.concept_id)
        artifact = generate_artifact(first_step, concept, case.learner_model)

        judges = [
            judge_gap_to_pedagogy(gap, workflow, graph),
            judge_modality_fit(workflow, case.learner_model, gap.target_concept_id),
            judge_adaptive_progression(
                gap, case.learner_model, case.expected_difficulty_band
            ),
        ]

    if trace_dir is not None:
        trace_dir.mkdir(parents=True, exist_ok=True)
        tracer.save_json(trace_dir / f"{case.case_id}.json")
        (trace_dir / f"{case.case_id}.md").write_text(tracer.render_markdown())

    return EvalResult(
        case_id=case.case_id,
        workflow=workflow,
        artifact_type=artifact.type,
        judge_results=judges,
    )


def render_table(results: list[EvalResult]) -> str:
    lines = []
    lines.append(
        "| Case | gap_to_pedagogy | modality_fit | adaptive_progression | Pass |"
    )
    lines.append("|------|-----------------|--------------|----------------------|------|")
    for r in results:
        scores = {j.judge_name: j.score for j in r.judge_results}
        lines.append(
            f"| {r.case_id} "
            f"| {scores.get('gap_to_pedagogy', 0):.2f} "
            f"| {scores.get('modality_fit', 0):.2f} "
            f"| {scores.get('adaptive_progression', 0):.2f} "
            f"| {'OK' if r.passed else 'FAIL'} |"
        )
    overall = sum(1 for r in results if r.passed) / max(len(results), 1)
    lines.append("")
    lines.append(f"**Overall pass rate:** {overall:.0%} ({sum(1 for r in results if r.passed)}/{len(results)})")
    return "\n".join(lines)


def render_rationale(results: list[EvalResult]) -> str:
    out = ["", "## Per-case judge rationales", ""]
    for r in results:
        out.append(f"### {r.case_id}")
        for j in r.judge_results:
            out.append(f"- **{j.judge_name}** ({j.score:.2f}): {j.rationale}")
        out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, help="Write results table to this file.")
    ap.add_argument(
        "--json-output", type=Path, help="Also write raw results as JSON."
    )
    ap.add_argument(
        "--verbose", action="store_true", help="Print per-judge rationales."
    )
    ap.add_argument(
        "--trace",
        type=Path,
        help="Write a full per-case reasoning trace (prompt + thinking + output) "
        "to this directory.",
    )
    args = ap.parse_args()

    cases = load_cases()
    if not cases:
        print("No golden cases found in evals/golden/", file=sys.stderr)
        return 1
    print(f"Running {len(cases)} eval cases...", file=sys.stderr)

    store = MemoryStore()
    results = []
    for case in cases:
        print(f"  [{case.case_id}] ...", file=sys.stderr)
        try:
            results.append(run_case(case, store, trace_dir=args.trace))
        except Exception as e:
            print(f"  [{case.case_id}] FAILED with {type(e).__name__}: {e}", file=sys.stderr)
            raise

    table = render_table(results)
    print(table)
    if args.verbose:
        print(render_rationale(results))

    if args.output:
        args.output.write_text(
            table + ("\n" + render_rationale(results) if args.verbose else "")
        )
    if args.json_output:
        args.json_output.write_text(
            json.dumps([r.model_dump(mode="json") for r in results], indent=2)
        )

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
