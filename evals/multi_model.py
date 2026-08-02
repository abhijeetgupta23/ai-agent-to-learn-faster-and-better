"""
Multi-model sweep: the SAME agent, the SAME 6 golden cases, the SAME three
pinned Claude judges — only the orchestrator model changes.

Each model in the sweep drives the autonomous loop (src/agent/autonomous.py)
end-to-end: Claude models via the Anthropic tool-use API, everything else
(DeepSeek, Kimi, GPT, ...) via the OpenAI-compatible tool loop. The judges are
byte-for-byte the ones evals/runner.py uses and stay pinned to
ADAPTIVE_LEARNING_JUDGE_MODEL, so scores are comparable across providers —
swapping the system under test never swaps the measuring stick.

Scoring surface is autonomous "teach" (B) — the lesson the model actually
delivered — plus "plan" (A) when the model elected to call plan_lessons. Same
honesty rules as evals/compare.py: a model that never diagnoses or never
teaches earns 0.0 "[no artifact]" fails, not silent skips.

Run:
  python -m evals.multi_model claude-sonnet-4-6 deepseek-reasoner kimi-k2-thinking gpt-5
  # or set ADAPTIVE_LEARNING_EVAL_MODELS=model1,model2 and run with no args.

Each model needs its provider's API key in the environment (see .env.example).

Outputs:
  - evals/results_multi_model.md   : model × judge table, pass rates, cost, tools.
  - evals/results_multi_model.json : raw per-model, per-case records.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from evals.autonomous_eval import run_autonomous_case, score_with_judges
from evals.compare import JUDGE_ORDER, PASS_THRESHOLD, _judges_to_dict, _mean, _passed, _retry
from evals.runner import _load_graph, load_cases
from src.harness import ExternalCallError
from src.memory.store import MemoryStore
from src.schemas import LearningGraph

OUT_MD = Path(__file__).parent / "results_multi_model.md"
OUT_JSON = Path(__file__).parent / "results_multi_model.json"


def sweep_models(argv: list[str]) -> list[str]:
    if argv:
        return argv
    env = os.environ.get("ADAPTIVE_LEARNING_EVAL_MODELS", "")
    return [m.strip() for m in env.split(",") if m.strip()]


def run_model(model: str, cases) -> dict:
    """All 6 golden cases through the autonomous agent on `model`, judged by
    the pinned judges. A fresh store per model — no cross-model learner state."""
    store = MemoryStore()
    records = []
    for case in cases:
        print(f"  [{model}] {case.case_id} ...", file=sys.stderr)
        graph: LearningGraph = _load_graph(case.domain_id, store)
        try:
            cap = _retry(lambda: run_autonomous_case(case, graph, store, model=model),
                         what=f"{model}/{case.case_id}")
        except ExternalCallError as e:
            # A model that errors permanently on a case (e.g. provider rejects
            # the request shape) is recorded as a hard failure, not a crash of
            # the whole sweep — the point is to see which models can drive the
            # agent at all.
            print(f"  [{model}] {case.case_id} FAILED: {e}", file=sys.stderr)
            records.append({"case_id": case.case_id, "error": str(e)})
            continue
        judges = _retry(lambda: score_with_judges(cap.gap, cap.teach_workflow, case, graph),
                        what=f"{model}/{case.case_id} judges")
        records.append({
            "case_id": case.case_id,
            "judges": _judges_to_dict(judges),
            "passed": _passed(judges),
            "cost_usd": round(cap.cost_usd, 4),
            "tool_calls": cap.tool_calls,
            "tool_sequence": cap.tool_sequence,
            "diagnosed": cap.gap is not None,
            "planned": cap.plan_workflow is not None,
            "taught": cap.teach_workflow is not None,
            "taught_concept_id": (cap.teach_workflow.target_concept_id if cap.teach_workflow else None),
            "taught_modality": (cap.teach_workflow.modality.value if cap.teach_workflow else None),
        })
    return {"model": model, "cases": records, "aggregate": _aggregate(records)}


def _aggregate(records: list[dict]) -> dict:
    scored = [r for r in records if "judges" in r]
    errored = [r for r in records if "error" in r]
    if not scored:
        return {"n_scored": 0, "n_errors": len(errored)}
    per_judge = {
        jn: round(_mean([r["judges"][jn]["score"] for r in scored]), 3) for jn in JUDGE_ORDER
    }
    return {
        "n_scored": len(scored),
        "n_errors": len(errored),
        "pass_rate": round(sum(r["passed"] for r in scored) / len(records), 3),
        "n_pass": sum(r["passed"] for r in scored),
        "n_total": len(records),
        "mean_score_per_judge": per_judge,
        "mean_overall_score": round(
            _mean([r["judges"][jn]["score"] for r in scored for jn in JUDGE_ORDER]), 3
        ),
        "total_cost_usd": round(sum(r["cost_usd"] for r in scored), 4),
        "mean_cost_usd": round(_mean([r["cost_usd"] for r in scored]), 4),
        "mean_tool_calls": round(_mean([r["tool_calls"] for r in scored]), 2),
        "full_rigor_rate": round(
            _mean([1.0 if (r["diagnosed"] and r["taught"]) else 0.0 for r in scored]), 3
        ),
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_markdown(data: dict) -> str:
    m = data["meta"]
    L: list[str] = []
    L.append("# Multi-model sweep — same agent, same cases, same judges")
    L.append("")
    L.append(
        f"Models under test: {', '.join('`' + x + '`' for x in m['models'])} · "
        f"Judges (pinned): `{m['judge_model']}` · "
        f"Pass = all 3 judges ≥ {m['pass_threshold']:.2f}"
    )
    L.append("")

    L.append("## Aggregate: model × metric")
    L.append("")
    L.append("| Model | Pass | Mean score | " + " | ".join(JUDGE_ORDER)
             + " | $/case | Tools/case | Diagnosed+taught | Errors |")
    L.append("|---|:---:|---:|" + "---:|" * len(JUDGE_ORDER) + "---:|---:|:---:|:---:|")
    for run in data["models"]:
        a = run["aggregate"]
        if not a.get("n_scored"):
            L.append(f"| `{run['model']}` | — | — |" + " — |" * len(JUDGE_ORDER)
                     + f" — | — | — | {a.get('n_errors', 0)} |")
            continue
        judge_cells = " | ".join(f"{a['mean_score_per_judge'][jn]:.2f}" for jn in JUDGE_ORDER)
        L.append(
            f"| `{run['model']}` | {a['n_pass']}/{a['n_total']} "
            f"| {a['mean_overall_score']:.2f} | {judge_cells} "
            f"| {a['mean_cost_usd']:.4f} | {a['mean_tool_calls']:.1f} "
            f"| {a['full_rigor_rate']:.0%} | {a['n_errors']} |"
        )
    L.append("")

    L.append("## Per-case pass/fail")
    L.append("")
    case_ids = m["case_ids"]
    L.append("| Model | " + " | ".join(case_ids) + " |")
    L.append("|---|" + ":---:|" * len(case_ids))
    for run in data["models"]:
        by_id = {r["case_id"]: r for r in run["cases"]}
        cells = []
        for cid in case_ids:
            r = by_id.get(cid)
            if r is None:
                cells.append("—")
            elif "error" in r:
                cells.append("ERR")
            else:
                cells.append("OK" if r["passed"] else "FAIL")
        L.append(f"| `{run['model']}` | " + " | ".join(cells) + " |")
    L.append("")

    L.append("## Per-case detail")
    L.append("")
    for run in data["models"]:
        L.append(f"### `{run['model']}`")
        L.append("")
        for r in run["cases"]:
            if "error" in r:
                L.append(f"- **{r['case_id']}**: ERROR — {r['error']}")
                continue
            scores = ", ".join(f"{jn}={r['judges'][jn]['score']:.2f}" for jn in JUDGE_ORDER)
            L.append(
                f"- **{r['case_id']}** ({'pass' if r['passed'] else 'fail'}): {scores} · "
                f"${r['cost_usd']:.4f} · tools: {' → '.join(r['tool_sequence']) or '(none)'} · "
                f"taught {r['taught_concept_id']} / {r['taught_modality']}"
            )
        L.append("")

    L.append("## Method notes")
    L.append("")
    L.append("- The three judges are identical across models — same functions, "
             "thresholds, and prompts as evals/runner.py, pinned to a Claude model "
             "so provider experiments never swap the graders.")
    L.append("- Scoring surface is autonomous 'teach' (B): the lesson each model "
             "actually delivered. No diagnose or no teach ⇒ honest 0.0 fails.")
    L.append("- Cost counts only system-under-test calls (judge calls are metered "
             "separately). Non-Anthropic pricing in src/harness/cost.py is list "
             "price at time of writing — verify before relying on it.")
    L.append("- 'Diagnosed+taught' = share of cases where the model both ran a "
             "diagnosis and delivered a lesson — the rigor floor the system "
             "prompt asks for.")
    L.append("")
    return "\n".join(L)


def main(argv: list[str]) -> int:
    models = sweep_models(argv)
    if not models:
        print("Usage: python -m evals.multi_model MODEL [MODEL ...]\n"
              "   or: ADAPTIVE_LEARNING_EVAL_MODELS=m1,m2 python -m evals.multi_model",
              file=sys.stderr)
        return 2

    cases = load_cases()
    if not cases:
        print("No golden cases found in evals/golden/", file=sys.stderr)
        return 1

    from src.llm import JUDGE_MODEL

    print(f"Sweeping {len(models)} models × {len(cases)} cases ...", file=sys.stderr)
    runs = [run_model(model, cases) for model in models]
    data = {
        "meta": {
            "models": models,
            "judge_model": JUDGE_MODEL,
            "pass_threshold": PASS_THRESHOLD,
            "judges": JUDGE_ORDER,
            "case_ids": [c.case_id for c in cases],
        },
        "models": runs,
    }
    OUT_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
    OUT_MD.write_text(render_markdown(data), encoding="utf-8")
    print(f"\nWrote {OUT_MD}\nWrote {OUT_JSON}", file=sys.stderr)
    for run in runs:
        a = run["aggregate"]
        if a.get("n_scored"):
            print(f"  {run['model']}: pass {a['n_pass']}/{a['n_total']} "
                  f"(mean {a['mean_overall_score']:.2f}, ${a['mean_cost_usd']:.4f}/case)",
                  file=sys.stderr)
        else:
            print(f"  {run['model']}: no scored cases ({a.get('n_errors', 0)} errors)",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
