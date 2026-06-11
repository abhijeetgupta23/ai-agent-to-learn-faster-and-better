"""
Evaluate the captured Naval demo result with the eval-harness judges.

The Naval demo (scripts/naval_demo.py) captured two live sessions into
docs/naval_use_case_trace.json but never scored them. This script feeds those
captured gap / workflow / learner objects through the same three judges the
golden eval suite uses (gap_to_pedagogy, modality_fit, adaptive_progression)
so the use-case claims get a numeric verdict instead of prose.

Run:
    python scripts/evaluate_naval.py
    python scripts/evaluate_naval.py --json-output docs/naval_eval_results.json
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
from src.schemas import (
    ConceptNode,
    GapEstimate,
    LearnerModel,
    LearningGraph,
    Workflow,
)

TRACE_PATH = Path("docs/naval_use_case_trace.json")

# Expected difficulty bands mirror the analogous golden cases:
#   psychology session is a prerequisite-backfill (like case_06 → band 2-3)
#   persuasion session is a novice start    (like case_01 → band 1-2)
EXPECTED_BANDS = {
    "psychology": (2, 3),
    "persuasion": (1, 2),
}


def _stub_graph(domain_id: str, node_ids: list[str]) -> LearningGraph:
    """
    The judges that need a graph only read concept_ids off it. Rebuild a minimal
    graph from the node_ids the trace recorded — name/description/difficulty are
    placeholders the judges never inspect.
    """
    return LearningGraph(
        domain_id=domain_id,
        domain_title=domain_id,
        source_hash="from-trace",
        nodes=[
            ConceptNode(
                concept_id=cid, name=cid, description="(from trace)", difficulty=1
            )
            for cid in node_ids
        ],
        edges=[],
    )


def evaluate_session(session: dict, domain_node_ids: list[str]) -> dict:
    domain = session["domain"]
    gap = GapEstimate.model_validate(session["gap"])
    workflow = Workflow.model_validate(session["workflow"])
    learner = LearnerModel.model_validate(session["learner"])
    graph = _stub_graph(domain, domain_node_ids)
    band = EXPECTED_BANDS[domain]

    print(f"  [{domain}] scoring with 3 judges...", file=sys.stderr)
    judges = [
        judge_gap_to_pedagogy(gap, workflow, graph),
        judge_modality_fit(workflow, learner, gap.target_concept_id),
        judge_adaptive_progression(gap, learner, band),
    ]
    return {
        "domain": domain,
        "target_concept_id": gap.target_concept_id,
        "modality": workflow.modality.value,
        "suggested_difficulty": gap.suggested_difficulty,
        "expected_band": list(band),
        "judges": [j.model_dump(mode="json") for j in judges],
        "passed": all(j.score >= 0.6 for j in judges),
    }


def render(results: list[dict]) -> str:
    lines = [
        "| Session | gap_to_pedagogy | modality_fit | adaptive_progression | Pass |",
        "|---------|-----------------|--------------|----------------------|------|",
    ]
    for r in results:
        s = {j["judge_name"]: j["score"] for j in r["judges"]}
        lines.append(
            f"| {r['domain']} "
            f"| {s.get('gap_to_pedagogy', 0):.2f} "
            f"| {s.get('modality_fit', 0):.2f} "
            f"| {s.get('adaptive_progression', 0):.2f} "
            f"| {'OK' if r['passed'] else 'FAIL'} |"
        )
    n_pass = sum(1 for r in results if r["passed"])
    lines.append("")
    lines.append(f"**Pass rate:** {n_pass}/{len(results)}")
    lines.append("")
    lines.append("## Judge rationales")
    for r in results:
        lines.append("")
        lines.append(f"### {r['domain']}")
        for j in r["judges"]:
            lines.append(f"- **{j['judge_name']}** ({j['score']:.2f}): {j['rationale']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-output", type=Path, help="Write raw results as JSON.")
    ap.add_argument("--output", type=Path, help="Write the markdown report here.")
    args = ap.parse_args()

    if not TRACE_PATH.exists():
        print(f"missing {TRACE_PATH} — run scripts/naval_demo.py first", file=sys.stderr)
        return 1
    trace = json.loads(TRACE_PATH.read_text())

    results = []
    for session in trace["sessions"]:
        node_ids = trace["domains"][session["domain"]]["node_ids"]
        results.append(evaluate_session(session, node_ids))

    report = render(results)
    print(report)
    if args.output:
        args.output.write_text(report + "\n")
    if args.json_output:
        args.json_output.write_text(json.dumps(results, indent=2))

    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
