"""
Cost analysis — computed from the real token counts captured in docs/traces/.

Run:
  PYTHONPATH=. python scripts/cost_analysis.py
  PYTHONPATH=. python scripts/cost_analysis.py --markdown > docs/COST_ANALYSIS.md

All per-operation numbers come from actual captured LLM calls (the trace JSON
files), not estimates. Scale projections are clearly labeled as projections.
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
from collections import defaultdict

# Anthropic list pricing, $/1M tokens (see shared model catalog).
PRICING = {
    "claude-opus-4-8": {"in": 5.00, "out": 25.00},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
    "claude-haiku-4-5": {"in": 1.00, "out": 5.00},
}
MODEL = "claude-opus-4-8"


def cost(inp: int, out: int, model: str = MODEL) -> float:
    p = PRICING[model]
    return inp / 1e6 * p["in"] + out / 1e6 * p["out"]


def load_calls() -> dict[str, list[tuple[int, int]]]:
    by_label: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for f in sorted(glob.glob("docs/traces/*.json")):
        d = json.load(open(f))
        for c in d["calls"]:
            u = c["usage"]
            by_label[c["label"]].append(
                (u.get("input_tokens", 0), u.get("output_tokens", 0))
            )
    return by_label


def avg(calls: list[tuple[int, int]]) -> tuple[float, float]:
    return (
        statistics.mean(c[0] for c in calls),
        statistics.mean(c[1] for c in calls),
    )


# Graph extraction is measured separately (one-time per domain, then cached).
# Numbers from a real traced extraction of domains/ai.md.
EXTRACT_IN, EXTRACT_OUT = 3647, 3728


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()

    by_label = load_calls()
    avgs = {label: avg(calls) for label, calls in by_label.items()}

    # Per-operation averages
    op_rows = []
    for label in ["diagnose", "plan", "generate:reading",
                  "judge:gap_to_pedagogy", "judge:modality_fit",
                  "judge:adaptive_progression"]:
        if label not in avgs:
            continue
        ai, ao = avgs[label]
        op_rows.append((label, ai, ao, cost(ai, ao)))

    # Derived aggregates
    diag = avgs.get("diagnose", (0, 0))
    plan = avgs.get("plan", (0, 0))
    gen = avgs.get("generate:reading", (0, 0))
    judges = [avgs.get(f"judge:{j}", (0, 0)) for j in
              ("gap_to_pedagogy", "modality_fit", "adaptive_progression")]

    # A learner-facing session: 1 diagnose + 1 plan + N generates (one per step).
    N_STEPS = 4
    session_in = diag[0] + plan[0] + N_STEPS * gen[0]
    session_out = diag[1] + plan[1] + N_STEPS * gen[1]
    session_cost = cost(session_in, session_out)

    # An eval case: diagnose + plan + 1 generate + 3 judges (what runner does).
    case_in = diag[0] + plan[0] + gen[0] + sum(j[0] for j in judges)
    case_out = diag[1] + plan[1] + gen[1] + sum(j[1] for j in judges)
    case_cost = cost(case_in, case_out)
    eval_run_cost = case_cost * 6  # 6 golden cases

    extract_cost = cost(EXTRACT_IN, EXTRACT_OUT)

    lines = []
    p = lines.append

    p("# Cost analysis\n")
    p("_All per-operation costs are computed from real token counts captured in "
      "`docs/traces/*.json` — actual LLM calls, not estimates. Pricing is "
      f"Anthropic list price for **{MODEL}** ($5.00 / 1M input, $25.00 / 1M "
      "output). Adaptive thinking is ON, which is included in the output "
      "tokens below._\n")

    p("## Per-operation cost (measured)\n")
    p("| Operation | avg input tok | avg output tok | cost/call |")
    p("|---|--:|--:|--:|")
    for label, ai, ao, c in op_rows:
        p(f"| `{label}` | {ai:,.0f} | {ao:,.0f} | ${c:.4f} |")
    p(f"| `extract_graph` (one-time/domain) | {EXTRACT_IN:,} | {EXTRACT_OUT:,} | ${extract_cost:.4f} |")
    p("")

    p("## Cost of one teaching session\n")
    p(f"A session = 1 diagnose + 1 plan + {N_STEPS} generated artifacts "
      f"(one per workflow step):\n")
    p(f"- **${session_cost:.3f} per session** "
      f"({session_in:,.0f} input + {session_out:,.0f} output tokens)")
    p(f"- The graph extraction (${extract_cost:.3f}) is **paid once per "
      f"domain**, then cached and reused across every learner — so it is "
      f"**not** part of per-session cost after the first learner.\n")

    p("## Cost of one eval run\n")
    p(f"An eval case = diagnose + plan + 1 generate + 3 judges:\n")
    p(f"- **${case_cost:.3f} per case**")
    p(f"- **${eval_run_cost:.2f} for the full 6-case suite**\n")
    p("The judges roughly double the cost of a case vs. a bare session — they "
      "are the price of *proving* the output is correct. You run them in CI / "
      "on changes, not per learner.\n")

    p("## Scale projection\n")
    p("_Projected from the measured per-session cost, assuming graph caching "
      "(extract-once-per-domain) is in effect._\n")
    p("| Scenario | Sessions | Cost |")
    p("|---|--:|--:|")
    for n in [1, 100, 1_000, 10_000, 100_000]:
        p(f"| {n:,} learner-sessions | {n:,} | ${session_cost * n:,.2f} |")
    p("")
    p(f"Plus a flat ~${extract_cost:.2f} per unique domain ingested (one-time).\n")

    # Optimization levers
    p("## Optimization levers (projected)\n")

    # Lever 1: prompt-cache the graph. The graph is re-sent in diagnose + plan.
    # Estimate graph share of input as the input delta between plan and generate
    # (generate doesn't include the full graph).
    graph_tokens = max(plan[0] - gen[0], 0)  # rough: plan carries graph, generate doesn't
    # If cached, repeated graph reads cost 0.1x instead of 1x. The graph is sent
    # in both diagnose and plan -> cache saves ~90% on the 2nd send.
    cache_saving_per_session = graph_tokens * (PRICING[MODEL]["in"] - PRICING[MODEL]["in"] * 0.1) / 1e6
    p(f"**1. Prompt-cache the learning graph.** The graph (~{graph_tokens:,.0f} "
      f"input tokens) is re-sent on every diagnose/plan/judge call within a "
      f"session. Caching it (cache reads cost ~0.1x) saves roughly "
      f"**${cache_saving_per_session:.3f}/session** on the repeated sends — "
      f"~{cache_saving_per_session / session_cost * 100:.0f}% of session cost. "
      f"The graph is a stable prefix, so this is a clean win. *(Not yet "
      f"implemented; the `MemoryStore` already isolates the graph as the "
      f"cacheable unit.)*\n")

    # Lever 2: cheaper model for judges + generate
    judge_in = sum(j[0] for j in judges)
    judge_out = sum(j[1] for j in judges)
    judge_opus = cost(judge_in, judge_out, "claude-opus-4-8")
    judge_haiku = cost(judge_in, judge_out, "claude-haiku-4-5")
    p(f"**2. Run judges on a cheaper model.** The three judges cost "
      f"${judge_opus:.3f}/case on Opus. On Haiku 4.5 ($1/$5) they'd cost "
      f"${judge_haiku:.3f}/case — a **{(1 - judge_haiku / judge_opus) * 100:.0f}% "
      f"cut** on the eval half of the bill. Judges apply tight rubrics with "
      f"deterministic signals pre-computed, so a smaller model is defensible "
      f"here; keep diagnose/plan on Opus where the reasoning matters.\n")

    gen_opus = cost(gen[0], gen[1], "claude-opus-4-8")
    gen_sonnet = cost(gen[0], gen[1], "claude-sonnet-4-6")
    p(f"**3. Generate artifacts on Sonnet.** Artifact generation is bulk "
      f"text, not hard reasoning: ${gen_opus:.4f}/artifact on Opus vs. "
      f"${gen_sonnet:.4f} on Sonnet 4.6 — and generate runs N times per "
      f"session, so this scales. Diagnose/plan (the actual decisions) stay on "
      f"Opus.\n")

    p("**4. Lower `effort` / disable thinking for generate.** Generation "
      "doesn't need deliberation — the trace already shows adaptive thinking "
      "skipping reasoning on `generate:reading` calls. Explicitly setting "
      "`effort: low` or thinking off for generate trims output tokens with no "
      "quality loss.\n")

    # Combined projection
    p("## Combined projection at 10k sessions/month\n")
    base = session_cost * 10_000
    # With graph cache + sonnet generate + haiku judges (judges only in eval, so
    # for pure learner sessions: graph cache + sonnet generate)
    opt_session_in = session_in
    opt_session_out = session_out
    # graph cache saving + generate-on-sonnet: recompute generate portion on sonnet
    gen_savings = N_STEPS * (gen_opus - gen_sonnet)
    opt_session_cost = session_cost - cache_saving_per_session - gen_savings
    opt = opt_session_cost * 10_000
    p(f"| Configuration | $/session | $/10k sessions |")
    p(f"|---|--:|--:|")
    p(f"| All-Opus, no caching (today) | ${session_cost:.3f} | ${base:,.0f} |")
    p(f"| + graph cache + Sonnet generate | ${opt_session_cost:.3f} | ${opt:,.0f} |")
    p(f"\nRoughly a **{(1 - opt / base) * 100:.0f}% reduction** on learner-"
      f"facing cost, before touching diagnose/plan quality.\n")

    p("## Honest caveats\n")
    p("- Numbers reflect adaptive thinking ON (the default), which adds output "
      "tokens — it's what makes the agent's reasoning auditable. Turning it "
      "off is cheaper but reverts to a black box.")
    p("- Sample size is small (the captured traces). Treat per-call costs as "
      "±20%; the *structure* (graph caching + tiered models is the big lever) "
      "holds regardless.")
    p("- List pricing; volume/commitment discounts and batch API (50% off, "
      "for non-interactive eval runs) are not modeled.")

    out = "\n".join(lines)
    if args.markdown:
        print(out)
    else:
        # Console summary
        print(f"Per session:      ${session_cost:.3f}")
        print(f"Per eval case:    ${case_cost:.3f}")
        print(f"Full eval run:    ${eval_run_cost:.2f}")
        print(f"Graph extract:    ${extract_cost:.3f} (one-time/domain)")
        print(f"\n10k sessions:     ${session_cost * 10_000:,.0f} (all-Opus)")


if __name__ == "__main__":
    main()
