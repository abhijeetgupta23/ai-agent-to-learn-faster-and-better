"""
Multi-trial variance harness (#2) — agents are non-deterministic, so a single
run is not a result.

Anthropic's vocabulary: a Task (golden case) is run over K Trials. We report:
  - pass@k : fraction of cases where AT LEAST ONE trial passed all judges
             (capability — can the agent do it at all).
  - pass^k : fraction of cases where ALL k trials passed — the metric that
             matters for a learner-facing tutor, where consistency is the
             product (Anthropic recommends pass^k for customer-facing agents).
  - per-judge stability : how often each judge returned the SAME verdict across
             a case's k trials. The judges are deterministic (temp 0, binary),
             so this should be ~1.0 — any drop is residual judge noise, and the
             rest of the variance is the AGENT moving (exactly the case_06 gap).

Judges are unchanged and pinned. Nothing here tunes them.

Run:  python run_variance.py --k 3
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from evals.autonomous_eval import run_autonomous_case, score_with_judges
from evals.runner import _load_graph, load_cases
from src.memory.store import MemoryStore
from src.schemas import EvalCase, LearningGraph

JUDGE_ORDER = ["gap_to_pedagogy", "modality_fit", "adaptive_progression"]
OUT_MD = Path(__file__).parent / "results_variance.md"
OUT_JSON = Path(__file__).parent / "results_variance.json"


def _trial(case: EvalCase, graph: LearningGraph, store: MemoryStore) -> dict:
    """One Trial: run the agent once, score it with the (deterministic) judges."""
    cap = run_autonomous_case(case.model_copy(deep=True), graph, store)
    judges = score_with_judges(cap.gap, cap.teach_workflow, case, graph)
    return {
        "passed": all(j.passed for j in judges),
        "verdicts": {j.judge_name: j.verdict for j in judges},
        "taught_concept": (cap.teach_workflow.target_concept_id if cap.teach_workflow else None),
        "taught_modality": (cap.teach_workflow.modality.value if cap.teach_workflow else None),
        "tool_sequence": cap.tool_sequence,
        "cost_usd": round(cap.cost_usd, 4),
    }


def run_variance(k: int) -> dict:
    cases = load_cases()
    if not cases:
        print("No golden cases found in evals/golden/", file=sys.stderr)
        sys.exit(1)
    store = MemoryStore()

    records = []
    for case in cases:
        graph = _load_graph(case.domain_id, store)
        trials = []
        for i in range(k):
            print(f"  [{case.case_id}] trial {i + 1}/{k} ...", file=sys.stderr)
            trials.append(_trial(case, graph, store))

        n_pass = sum(1 for t in trials if t["passed"])
        judge_stats = {}
        for jn in JUDGE_ORDER:
            verds = [t["verdicts"].get(jn) for t in trials]
            counts = Counter(verds)
            judge_stats[jn] = {
                "distribution": dict(counts),
                "stable": len(set(verds)) == 1,
                "majority": counts.most_common(1)[0][0],
            }
        records.append({
            "case_id": case.case_id,
            "n_pass": n_pass,
            "all_pass": n_pass == k,   # -> pass^k
            "any_pass": n_pass >= 1,   # -> pass@k
            "flippy": 0 < n_pass < k,  # inconsistent across trials
            "taught_modalities": sorted({t["taught_modality"] for t in trials if t["taught_modality"]}),
            "judge_stats": judge_stats,
            "trials": trials,
            "cost_usd": round(sum(t["cost_usd"] for t in trials), 4),
        })

    n = len(records)
    aggregate = {
        "k": k,
        "n_cases": n,
        "pass_at_k": round(sum(r["any_pass"] for r in records) / n, 3),
        "pass_pow_k": round(sum(r["all_pass"] for r in records) / n, 3),
        "flippy_cases": [r["case_id"] for r in records if r["flippy"]],
        "judge_stability": {
            jn: round(sum(r["judge_stats"][jn]["stable"] for r in records) / n, 3)
            for jn in JUDGE_ORDER
        },
        "total_cost_usd": round(sum(r["cost_usd"] for r in records), 4),
    }
    return {"meta": _meta(k), "cases": records, "aggregate": aggregate}


def _meta(k: int) -> dict:
    from src.llm import DEFAULT_MODEL, JUDGE_MODEL

    return {
        "k": k,
        "agent_model": DEFAULT_MODEL,
        "judge_model": JUDGE_MODEL,
        "judges": JUDGE_ORDER,
        "notes": [
            "pass^k = ALL k trials of a case pass; pass@k = at least one passes.",
            "Judges are deterministic (binary, temp 0), so judge_stability ~1.0 "
            "and the measured spread is the agent's run-to-run variance.",
            "A 'flippy' case passes some trials and fails others — the single-run "
            "headline number is unreliable for it.",
        ],
    }


def render_markdown(data: dict) -> str:
    m, agg = data["meta"], data["aggregate"]
    L: list[str] = []
    L.append(f"# Variance over {m['k']} trials per case")
    L.append("")
    L.append(f"Agent `{m['agent_model']}` · judges (pinned, deterministic) `{m['judge_model']}`")
    L.append("")
    L.append("## Aggregate")
    L.append("")
    L.append(f"- **pass^{m['k']}** (all {m['k']} trials pass — the consistency metric): "
             f"**{agg['pass_pow_k']:.0%}**")
    L.append(f"- **pass@{m['k']}** (at least one trial passes): {agg['pass_at_k']:.0%}")
    L.append(f"- flippy cases (inconsistent across trials): "
             f"{', '.join(agg['flippy_cases']) or 'none'}")
    L.append(f"- judge stability (same verdict across trials): "
             + ", ".join(f"{jn} {s:.0%}" for jn, s in agg['judge_stability'].items()))
    L.append(f"- total cost: ${agg['total_cost_usd']:.2f}")
    L.append("")
    L.append("## Per case")
    L.append("")
    L.append(f"| Case | passed | flippy | modalities taught | gap | modality | adaptive | $ |")
    L.append("|------|:------:|:------:|-------------------|:---:|:--------:|:--------:|--:|")
    for r in data["cases"]:
        js = r["judge_stats"]
        stab = lambda jn: "stable" if js[jn]["stable"] else "FLIPS " + "/".join(
            f"{v}x{n}" for v, n in js[jn]["distribution"].items()
        )
        L.append(
            f"| {r['case_id']} | {r['n_pass']}/{m['k']} "
            f"| {'yes' if r['flippy'] else '—'} "
            f"| {', '.join(r['taught_modalities'])} "
            f"| {stab('gap_to_pedagogy')} | {stab('modality_fit')} | {stab('adaptive_progression')} "
            f"| {r['cost_usd']:.3f} |"
        )
    L.append("")
    for note in m["notes"]:
        L.append(f"> {note}")
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=3, help="Trials per case (default 3).")
    args = ap.parse_args()
    print(f"Running variance harness: {args.k} trials per case...", file=sys.stderr)
    data = run_variance(args.k)
    OUT_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
    OUT_MD.write_text(render_markdown(data), encoding="utf-8")
    agg = data["aggregate"]
    print(f"\nWrote {OUT_MD}\nWrote {OUT_JSON}", file=sys.stderr)
    print(f"\npass^{args.k}={agg['pass_pow_k']:.0%}  pass@{args.k}={agg['pass_at_k']:.0%}  "
          f"flippy={agg['flippy_cases'] or 'none'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
