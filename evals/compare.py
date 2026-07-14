"""
Head-to-head: workflow mode vs autonomous mode, one harness, the SAME three
pinned judges.

For each of the 6 golden cases this runs:
  - workflow mode          : fixed diagnose -> plan -> generate pipeline.
  - autonomous mode (ONE kickoff turn), scored two honest ways:
      * teach (B) : a Workflow synthesized from the lesson the model actually
                    taught — autonomous mode's true peer of the workflow plan.
      * plan (A)  : the Workflow from the model's optional `plan_lessons` call
                    (None when the model taught directly without planning).

The judges are byte-for-byte the same functions used by evals/runner.py — this
driver never alters their criteria, thresholds, or prompts. The autonomous
A/B scorings come from a SINGLE autonomous run, so cost and tool-call count are
attributed once to that run (not double-counted across A and B).

Outputs:
  - evals/results_comparison.md   : side-by-side tables + pass/fail + aggregates.
  - evals/results_comparison.json : raw per-case, per-judge {score, rationale}.

Run:  python -m evals.compare         (loads .env via run_compare.py, or set
                                       ANTHROPIC_API_KEY in the environment)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from evals.autonomous_eval import run_autonomous_case, score_with_judges
from evals.judges import (
    judge_adaptive_progression,
    judge_gap_to_pedagogy,
    judge_modality_fit,
)
from evals.runner import load_cases, _load_graph, run_workflow_case
from src.harness import ExternalCallError
from src.memory.store import MemoryStore
from src.schemas import JudgeResult, LearningGraph

PASS_THRESHOLD = 0.6  # identical to EvalResult.passed — NOT a judge change.
JUDGE_ORDER = ["gap_to_pedagogy", "modality_fit", "adaptive_progression"]

OUT_MD = Path(__file__).parent / "results_comparison.md"
OUT_JSON = Path(__file__).parent / "results_comparison.json"


def _judges_to_dict(judges: list[JudgeResult]) -> dict:
    return {j.judge_name: {"score": j.score, "rationale": j.rationale} for j in judges}


def _passed(judges: list[JudgeResult]) -> bool:
    return all(j.score >= PASS_THRESHOLD for j in judges)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _retry(fn, *, what: str, attempts: int = 4):
    """Re-run a case stage on a TRANSIENT external-call failure (the built-in
    src/llm.py retries cover momentary blips; this covers a longer network
    outage spanning a whole turn). Permanent failures are re-raised immediately."""
    for i in range(attempts):
        try:
            return fn()
        except ExternalCallError as e:
            if not getattr(e, "transient", False) or i == attempts - 1:
                raise
            wait = 5 * (i + 1)
            print(f"    {what}: transient failure ({e}); retry {i + 1}/{attempts - 1} "
                  f"in {wait}s", file=sys.stderr)
            time.sleep(wait)


def run_comparison() -> dict:
    cases = load_cases()
    if not cases:
        print("No golden cases found in evals/golden/", file=sys.stderr)
        sys.exit(1)

    # Each mode gets its OWN store so neither pollutes the other's learner state.
    store_wf = MemoryStore()
    store_auto = MemoryStore()

    records = []
    for case in cases:
        print(f"  [{case.case_id}] workflow ...", file=sys.stderr)
        graph: LearningGraph = _load_graph(case.domain_id, store_wf)
        wf = _retry(lambda: run_workflow_case(case, graph, store_wf),
                    what=f"{case.case_id} workflow")
        wf_judges = _retry(lambda: [
            judge_gap_to_pedagogy(wf.gap, wf.workflow, graph),
            judge_modality_fit(wf.workflow, case.learner_model, wf.gap.target_concept_id),
            judge_adaptive_progression(wf.gap, case.learner_model, case.expected_difficulty_band),
        ], what=f"{case.case_id} workflow-judges")

        print(f"  [{case.case_id}] autonomous ...", file=sys.stderr)
        graph_a: LearningGraph = _load_graph(case.domain_id, store_auto)
        cap = _retry(lambda: run_autonomous_case(case, graph_a, store_auto),
                     what=f"{case.case_id} autonomous")
        # Same single run, scored two ways. judge 3 (adaptive_progression) is
        # identical across A and B (both read cap.gap).
        teach_judges = _retry(lambda: score_with_judges(cap.gap, cap.teach_workflow, case, graph_a),
                              what=f"{case.case_id} teach-judges")
        plan_judges = _retry(lambda: score_with_judges(cap.gap, cap.plan_workflow, case, graph_a),
                             what=f"{case.case_id} plan-judges")

        records.append({
            "case_id": case.case_id,
            "description": case.description,
            "expected": {
                "target_concept": case.expected_target_concept,
                "modality": case.expected_modality.value,
                "difficulty_band": list(case.expected_difficulty_band),
            },
            "workflow": {
                "judges": _judges_to_dict(wf_judges),
                "passed": _passed(wf_judges),
                "cost_usd": round(wf.cost_usd, 4),
                "tool_calls": wf.tool_calls,
                "tool_sequence": wf.tool_sequence,
                "target_concept_id": wf.gap.target_concept_id,
                "suggested_difficulty": wf.gap.suggested_difficulty,
                "primary_modality": wf.workflow.modality.value,
                "n_steps": len(wf.workflow.steps),
            },
            "autonomous": {
                # Run-level facts (one turn) — cost/tools attributed ONCE here.
                "cost_usd": round(cap.cost_usd, 4),
                "tool_calls": cap.tool_calls,
                "tool_sequence": cap.tool_sequence,
                "diagnosed": cap.gap is not None,
                "planned": cap.plan_workflow is not None,
                "taught": cap.teach_workflow is not None,
                "suggested_difficulty": (cap.gap.suggested_difficulty if cap.gap else None),
                "taught_concept_id": (cap.teach_workflow.target_concept_id if cap.teach_workflow else None),
                "taught_modality": (cap.teach_workflow.modality.value if cap.teach_workflow else None),
                "n_steps_teach": (len(cap.teach_workflow.steps) if cap.teach_workflow else 0),
                "final_text": cap.final_text,
                # Two honest scorings of that one run.
                "teach": {  # surface B — the recommended peer
                    "judges": _judges_to_dict(teach_judges),
                    "passed": _passed(teach_judges),
                },
                "plan": {  # surface A — optional intermediate
                    "judges": _judges_to_dict(plan_judges),
                    "passed": _passed(plan_judges),
                    "available": cap.plan_workflow is not None,
                },
            },
        })

    return {
        "meta": _meta(),
        "cases": records,
        "aggregate": _aggregate(records),
    }


def _meta() -> dict:
    from src.llm import DEFAULT_MODEL, JUDGE_MODEL

    return {
        "system_under_test_model": DEFAULT_MODEL,
        "judge_model": JUDGE_MODEL,
        "n_cases": 6,
        "pass_threshold": PASS_THRESHOLD,
        "judges": JUDGE_ORDER,
        "notes": [
            "The three judges are identical across modes — same functions, "
            "thresholds, and prompts as evals/runner.py. Nothing here tunes them.",
            "Autonomous 'teach' (B) is judged on the lesson the model actually "
            "delivered; 'plan' (A) on its optional plan_lessons call.",
            "CAVEAT: the synthesized teach-Workflow (B) has 1 step, vs 3-5 in "
            "workflow mode. judge_gap_to_pedagogy inspects 'all steps' and is "
            "therefore structurally lenient toward B. Disclosed, not corrected, "
            "to avoid changing the judge.",
            "judge_adaptive_progression reads only the gap and is identical for "
            "autonomous A and B (both from the same diagnose call).",
            "Cost excludes judge calls (the measuring stick) and counts only "
            "system-under-test calls, metered identically in both modes.",
        ],
    }


def _aggregate(records: list[dict]) -> dict:
    def agg(selector) -> dict:
        rows = [selector(r) for r in records]
        per_judge = {
            jn: round(_mean([row["judges"][jn]["score"] for row in rows]), 3)
            for jn in JUDGE_ORDER
        }
        n_pass = sum(1 for row in rows if row["passed"])
        return {
            "pass_rate": round(n_pass / len(rows), 3),
            "n_pass": n_pass,
            "n_total": len(rows),
            "mean_score_per_judge": per_judge,
            "mean_overall_score": round(
                _mean([row["judges"][jn]["score"] for row in rows for jn in JUDGE_ORDER]), 3
            ),
        }

    wf_cost = [r["workflow"]["cost_usd"] for r in records]
    au_cost = [r["autonomous"]["cost_usd"] for r in records]
    wf_tools = [r["workflow"]["tool_calls"] for r in records]
    au_tools = [r["autonomous"]["tool_calls"] for r in records]

    return {
        "workflow": {
            **agg(lambda r: r["workflow"]),
            "total_cost_usd": round(sum(wf_cost), 4),
            "mean_cost_usd": round(_mean(wf_cost), 4),
            "mean_tool_calls": round(_mean(wf_tools), 2),
        },
        "autonomous_teach": {
            **agg(lambda r: r["autonomous"]["teach"]),
            "total_cost_usd": round(sum(au_cost), 4),
            "mean_cost_usd": round(_mean(au_cost), 4),
            "mean_tool_calls": round(_mean(au_tools), 2),
        },
        "autonomous_plan": {
            **agg(lambda r: r["autonomous"]["plan"]),
            "n_with_plan": sum(1 for r in records if r["autonomous"]["planned"]),
        },
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _fmt(score: float) -> str:
    return f"{score:.2f}"


def render_markdown(data: dict) -> str:
    m = data["meta"]
    L: list[str] = []
    L.append("# Workflow vs Autonomous — head-to-head eval")
    L.append("")
    L.append(
        f"System under test: `{m['system_under_test_model']}` · "
        f"Judges (pinned): `{m['judge_model']}` · "
        f"Pass = all 3 judges ≥ {m['pass_threshold']:.2f}"
    )
    L.append("")
    L.append(
        "Two orchestration architectures, one harness, the same three judges. "
        "`Auto(teach)` scores the lesson the model actually delivered; "
        "`Auto(plan)` scores its optional `plan_lessons` call."
    )
    L.append("")

    # --- Per-case, per-judge table -----------------------------------------
    L.append("## Scores: case × judge × mode")
    L.append("")
    L.append("| Case | Judge | Workflow | Auto (teach, B) | Auto (plan, A) |")
    L.append("|------|-------|---------:|----------------:|---------------:|")
    for r in data["cases"]:
        wfj = r["workflow"]["judges"]
        tbj = r["autonomous"]["teach"]["judges"]
        plj = r["autonomous"]["plan"]["judges"]
        plan_avail = r["autonomous"]["plan"]["available"]
        for i, jn in enumerate(JUDGE_ORDER):
            case_cell = r["case_id"] if i == 0 else ""
            pl = _fmt(plj[jn]["score"]) if plan_avail else "—"
            L.append(
                f"| {case_cell} | {jn} | {_fmt(wfj[jn]['score'])} "
                f"| {_fmt(tbj[jn]['score'])} | {pl} |"
            )
    L.append("")

    # --- Pass/fail + ops table ---------------------------------------------
    L.append("## Pass/fail, cost, and tool-call count per case")
    L.append("")
    L.append(
        "| Case | WF pass | Auto(teach) pass | Auto(plan) pass | "
        "WF $ | Auto $ | WF tools | Auto tools | Auto tool sequence |"
    )
    L.append(
        "|------|:------:|:----------------:|:---------------:|"
        "-----:|-------:|--------:|----------:|--------------------|"
    )
    for r in data["cases"]:
        a = r["autonomous"]
        plan_pass = "OK" if a["plan"]["passed"] else ("FAIL" if a["planned"] else "—")
        L.append(
            f"| {r['case_id']} "
            f"| {'OK' if r['workflow']['passed'] else 'FAIL'} "
            f"| {'OK' if a['teach']['passed'] else 'FAIL'} "
            f"| {plan_pass} "
            f"| {r['workflow']['cost_usd']:.4f} "
            f"| {a['cost_usd']:.4f} "
            f"| {r['workflow']['tool_calls']} "
            f"| {a['tool_calls']} "
            f"| {' → '.join(a['tool_sequence']) or '(none)'} |"
        )
    L.append("")

    # --- Aggregate ----------------------------------------------------------
    agg = data["aggregate"]
    L.append("## Aggregate")
    L.append("")
    L.append("| Metric | Workflow | Auto (teach, B) | Auto (plan, A) |")
    L.append("|--------|---------:|----------------:|---------------:|")
    wf, at, ap = agg["workflow"], agg["autonomous_teach"], agg["autonomous_plan"]
    L.append(
        f"| Pass rate | {wf['pass_rate']:.0%} ({wf['n_pass']}/{wf['n_total']}) "
        f"| {at['pass_rate']:.0%} ({at['n_pass']}/{at['n_total']}) "
        f"| {ap['pass_rate']:.0%} ({ap['n_pass']}/{ap['n_total']}) |"
    )
    for jn in JUDGE_ORDER:
        L.append(
            f"| mean {jn} | {wf['mean_score_per_judge'][jn]:.2f} "
            f"| {at['mean_score_per_judge'][jn]:.2f} "
            f"| {ap['mean_score_per_judge'][jn]:.2f} |"
        )
    L.append(
        f"| mean overall score | {wf['mean_overall_score']:.2f} "
        f"| {at['mean_overall_score']:.2f} | {ap['mean_overall_score']:.2f} |"
    )
    L.append(
        f"| mean cost / case (USD) | {wf['mean_cost_usd']:.4f} "
        f"| {at['mean_cost_usd']:.4f} | (same run as teach) |"
    )
    L.append(
        f"| mean tool calls / case | {wf['mean_tool_calls']:.1f} "
        f"| {at['mean_tool_calls']:.1f} | (same run as teach) |"
    )
    L.append("")

    # --- Rationales ---------------------------------------------------------
    L.append("## Per-case judge rationales")
    L.append("")
    for r in data["cases"]:
        L.append(f"### {r['case_id']}")
        L.append(f"_{r['description']}_")
        L.append("")
        a = r["autonomous"]
        L.append(
            f"- Autonomous tool path: `{' → '.join(a['tool_sequence']) or '(none)'}` "
            f"· diagnosed={a['diagnosed']} planned={a['planned']} taught={a['taught']} "
            f"· taught {a['taught_concept_id']} / {a['taught_modality']}"
        )
        if a["final_text"]:
            L.append(f"- Autonomous closing note: \"{a['final_text'].strip()}\"")
        L.append("")
        for jn in JUDGE_ORDER:
            L.append(f"**{jn}**")
            L.append(f"- Workflow ({_fmt(r['workflow']['judges'][jn]['score'])}): "
                     f"{r['workflow']['judges'][jn]['rationale']}")
            L.append(f"- Auto(teach) ({_fmt(a['teach']['judges'][jn]['score'])}): "
                     f"{a['teach']['judges'][jn]['rationale']}")
            if a["plan"]["available"]:
                L.append(f"- Auto(plan) ({_fmt(a['plan']['judges'][jn]['score'])}): "
                         f"{a['plan']['judges'][jn]['rationale']}")
            L.append("")

    # --- Method notes -------------------------------------------------------
    L.append("## Method & honesty notes")
    L.append("")
    for n in m["notes"]:
        L.append(f"- {n}")
    L.append("")
    return "\n".join(L)


def main() -> int:
    print("Running head-to-head comparison (6 cases × 2 modes)...", file=sys.stderr)
    data = run_comparison()
    OUT_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
    OUT_MD.write_text(render_markdown(data), encoding="utf-8")
    print(f"\nWrote {OUT_MD}\nWrote {OUT_JSON}", file=sys.stderr)

    agg = data["aggregate"]
    wf, at = agg["workflow"], agg["autonomous_teach"]
    print(
        f"\nWorkflow pass {wf['n_pass']}/{wf['n_total']} (mean {wf['mean_overall_score']:.2f}) | "
        f"Autonomous-teach pass {at['n_pass']}/{at['n_total']} (mean {at['mean_overall_score']:.2f})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
