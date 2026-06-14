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
from dataclasses import dataclass, field
from pathlib import Path

from evals.judges import (
    judge_adaptive_progression,
    judge_gap_to_pedagogy,
    judge_modality_fit,
)
from src.graph.extractor import extract_learning_graph
from src.harness import cost
from src.memory.store import MemoryStore
from src.schemas import (
    EvalCase,
    EvalResult,
    GapEstimate,
    LearningGraph,
    Modality,
    Workflow,
    WorkflowStep,
)
from src.tools import diagnose_learner, generate_artifact, plan_workflow
from src.trace import trace

GOLDEN_DIR = Path(__file__).parent / "golden"
DOMAINS_DIR = Path(__file__).parent.parent / "domains"


def load_cases() -> list[EvalCase]:
    cases = []
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        # Explicit utf-8: golden descriptions use em-dashes, and Windows would
        # otherwise decode them as cp1252 (mojibake) by default.
        cases.append(EvalCase.model_validate_json(path.read_text(encoding="utf-8")))
    return cases


def _load_graph(domain_id: str, store: MemoryStore) -> LearningGraph:
    """
    Eval graphs are checked into evals/golden/graphs/ — deterministic, so we
    don't pay LLM cost (or non-determinism) for graph extraction during evals.
    """
    graph_path = GOLDEN_DIR / "graphs" / f"{domain_id}.json"
    if graph_path.exists():
        graph = LearningGraph.model_validate_json(graph_path.read_text(encoding="utf-8"))
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


@dataclass
class WorkflowCapture:
    """What the WORKFLOW-mode pipeline exposed to the eval surfaces, mirroring
    AutonomousCapture so the head-to-head driver treats both modes uniformly."""

    case_id: str
    gap: GapEstimate
    workflow: Workflow
    artifact_type: str
    cost_usd: float = 0.0
    # The fixed pipeline runs three tools per case: diagnose, plan, generate.
    tool_calls: int = 3
    tool_sequence: list[str] = field(default_factory=lambda: ["diagnose", "plan_lessons", "teach"])


def run_workflow_case(
    case: EvalCase, graph: LearningGraph, store: MemoryStore, trace_dir: Path | None = None
) -> WorkflowCapture:
    """Run the fixed diagnose -> plan -> generate pipeline and capture the
    judge-facing artifacts plus cost. Judges are NOT run here (the caller scores)
    so judge spend is never charged to the mode."""
    with trace(case.case_id) as tracer:
        # Meter ONLY the system-under-test calls. Judge calls happen in the
        # caller, outside this meter — same discipline as autonomous mode.
        with cost.meter() as meter:
            gap = diagnose_learner(case.learner_model, graph)
            workflow = plan_workflow(gap, case.learner_model, graph)

            # Generate the first step's artifact — enough to record the artifact
            # type (the modality is what we score).
            first_step: WorkflowStep = workflow.steps[0]
            concept = graph.node_by_id(first_step.concept_id)
            artifact = generate_artifact(first_step, concept, case.learner_model)

    if trace_dir is not None:
        trace_dir.mkdir(parents=True, exist_ok=True)
        tracer.save_json(trace_dir / f"{case.case_id}.json")
        (trace_dir / f"{case.case_id}.md").write_text(tracer.render_markdown())

    return WorkflowCapture(
        case_id=case.case_id,
        gap=gap,
        workflow=workflow,
        artifact_type=artifact.type,
        cost_usd=meter.total_usd,
    )


def _placeholder_workflow(gap: GapEstimate | None) -> Workflow:
    """Container Workflow for an autonomous turn that taught nothing — the judges
    have already recorded the miss; this only fills EvalResult.workflow."""
    return Workflow(
        target_concept_id=(gap.target_concept_id if gap else "none"),
        modality=Modality.READING,
        steps=[],
        rationale="[no lesson taught this turn]",
    )


def run_case(
    case: EvalCase,
    store: MemoryStore,
    trace_dir: Path | None = None,
    mode: str = "workflow",
) -> EvalResult:
    """Score one golden case in `mode` ('workflow' or 'autonomous') with the
    SAME three pinned judges. Autonomous mode is judged on the lesson it actually
    taught (the `teach` call, surface B)."""
    graph = _load_graph(case.domain_id, store)

    if mode == "autonomous":
        # Imported lazily so the default workflow path has no autonomous deps.
        from evals.autonomous_eval import run_autonomous_case, score_with_judges

        cap = run_autonomous_case(case, graph, store)
        judges = score_with_judges(cap.gap, cap.teach_workflow, case, graph)
        return EvalResult(
            case_id=case.case_id,
            workflow=cap.teach_workflow or _placeholder_workflow(cap.gap),
            artifact_type=cap.artifact_type or "none",
            judge_results=judges,
        )

    wf = run_workflow_case(case, graph, store, trace_dir=trace_dir)
    judges = [
        judge_gap_to_pedagogy(wf.gap, wf.workflow, graph),
        judge_modality_fit(wf.workflow, case.learner_model, wf.gap.target_concept_id),
        judge_adaptive_progression(
            wf.gap, case.learner_model, case.expected_difficulty_band
        ),
    ]
    return EvalResult(
        case_id=case.case_id,
        workflow=wf.workflow,
        artifact_type=wf.artifact_type,
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
    ap.add_argument(
        "--mode",
        choices=["workflow", "autonomous"],
        default="workflow",
        help="Orchestration mode to score with the same three judges. "
        "'workflow' = fixed diagnose->plan->generate pipeline (default, baseline). "
        "'autonomous' = model-owned tool loop, judged on the lesson it taught.",
    )
    args = ap.parse_args()

    cases = load_cases()
    if not cases:
        print("No golden cases found in evals/golden/", file=sys.stderr)
        return 1
    print(f"Running {len(cases)} eval cases in '{args.mode}' mode...", file=sys.stderr)

    store = MemoryStore()
    results = []
    for case in cases:
        print(f"  [{case.case_id}] ...", file=sys.stderr)
        try:
            results.append(run_case(case, store, trace_dir=args.trace, mode=args.mode))
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
