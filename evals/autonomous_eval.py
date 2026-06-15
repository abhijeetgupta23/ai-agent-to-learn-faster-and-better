"""
Run a golden case through AUTONOMOUS mode and capture exactly what the three
pinned judges consume.

The judges (evals/judges/) score two decision artifacts: a `GapEstimate` and a
`Workflow`. Workflow mode produces both directly (diagnose_learner /
plan_workflow). Autonomous mode is the model-owned loop (src/agent/autonomous.py)
— it produces those same artifacts *only if it elects to*, and its real native
decision is the `teach` call. So this module captures three things from ONE
kickoff turn and feeds them to the UNCHANGED judges:

  - gap        : the `GapEstimate` from the model's `diagnose` call (state["last_gap"]).
  - plan (A)   : the `Workflow` from the model's optional `plan_lessons` call.
  - teach (B)  : a `Workflow` SYNTHESIZED from the lesson the model actually
                 taught (the `teach` call) — autonomous mode's true peer of
                 workflow mode's plan.

Nothing here touches judge criteria, thresholds, or prompts. The adapter only
translates autonomous mode's native output into the struct vocabulary the
judges already read. Honesty guardrails:
  - If the model never diagnoses, there is no gap → judges 1 & 3 cannot score
    → recorded as a structural miss (score 0.0, rationale "[no artifact]"),
    NOT papered over.
  - If the model never teaches, there is no teach-Workflow (B). Same for plan (A).
  - The synthesized teach-Workflow (B) has ONE step (the lesson delivered),
    whereas workflow-mode Workflows have 3-5. judge_gap_to_pedagogy inspects
    "all steps" and is therefore structurally lenient on B. This asymmetry is
    disclosed in the comparison report, not masked by padding fake steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from evals.judges import (
    judge_adaptive_progression,
    judge_gap_to_pedagogy,
    judge_modality_fit,
)
from src.agent.autonomous import kickoff_message, run_agent_turn
from src.harness import cost
from src.memory.store import MemoryStore
from src.schemas import (
    EvalCase,
    GapEstimate,
    JudgeResult,
    LearningGraph,
    Workflow,
    WorkflowStep,
)


@dataclass
class AutonomousCapture:
    """Everything one autonomous kickoff turn exposed to the eval surfaces."""

    case_id: str
    gap: GapEstimate | None = None
    plan_workflow: Workflow | None = None   # A: from `plan_lessons`, if called
    teach_workflow: Workflow | None = None  # B: synthesized from `teach` call(s)
    taught_steps: list[WorkflowStep] = field(default_factory=list)
    artifact_type: str | None = None
    final_text: str = ""
    tool_calls: int = 0
    tool_sequence: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    # Observability: the ordered stream of everything the agent emitted this turn
    # (tool calls, results, gap, workflow, artifact, final text) — the trace we
    # read for error analysis.
    events: list[dict] = field(default_factory=list)


def _synthesize_teach_workflow(
    steps: list[WorkflowStep], gap: GapEstimate | None, final_text: str
) -> Workflow | None:
    """Translate the model's actual `teach` decision into the Workflow shape the
    judges read. One step in == one step out — no fabricated padding."""
    if not steps:
        return None
    primary = steps[0]
    return Workflow(
        target_concept_id=primary.concept_id,
        modality=primary.modality,
        steps=list(steps),
        # The model's stated "why" for the lesson it delivered. Falls back to the
        # step objective if the model ended its turn without prose.
        rationale=final_text.strip() or primary.objective,
    )


def run_autonomous_case(case: EvalCase, graph: LearningGraph, store: MemoryStore) -> AutonomousCapture:
    """Run ONE autonomous kickoff turn over the case learner and capture the
    judge-facing artifacts, plus cost and tool-call count."""
    cap = AutonomousCapture(case_id=case.case_id)

    state: dict = {
        "messages": [],
        "learner": case.learner_model,
        "graph": graph,
        "store": store,
    }

    def emit(event: str, payload: dict) -> None:
        cap.events.append({"event": event, "payload": payload})
        if event == "tool_call":
            cap.tool_calls += 1
            cap.tool_sequence.append(payload.get("tool", "?"))
        elif event == "artifact":
            step = WorkflowStep.model_validate(payload["step"])
            cap.taught_steps.append(step)
            cap.artifact_type = payload.get("artifact", {}).get("type", cap.artifact_type)

    # Meter ONLY the system-under-test calls (diagnose/plan/teach inside the
    # loop). Judge calls are metered separately and never charged to the mode.
    with cost.meter() as meter:
        final_text = run_agent_turn(state, kickoff_message(case.learner_model, graph), emit)
    cap.cost_usd = meter.total_usd
    cap.final_text = final_text or ""

    cap.gap = state.get("last_gap")
    cap.plan_workflow = state.get("last_workflow")
    cap.teach_workflow = _synthesize_teach_workflow(cap.taught_steps, cap.gap, cap.final_text)
    return cap


# ---------------------------------------------------------------------------
# Scoring — the SAME three judges, called with the SAME signatures as
# evals/runner.py. The only branch here is for missing artifacts, which become
# honest "[no artifact]" fails rather than silently-skipped scores.
# ---------------------------------------------------------------------------

_MISSING_REASONS = {
    "gap_to_pedagogy": "model produced no {missing} this turn — nothing for the judge to score",
    "modality_fit": "model produced no {missing} this turn — nothing for the judge to score",
    "adaptive_progression": "model produced no diagnosis (no `diagnose` call) this turn",
}


def _missing(judge_name: str, missing: str) -> JudgeResult:
    # A structurally missing artifact is a fail (the mode didn't produce the
    # decision the judge measures) — not an `abstain`, which is for borderline
    # calls the judge could see but couldn't confidently decide.
    return JudgeResult(
        judge_name=judge_name,
        verdict="fail",
        rationale="[no artifact] " + _MISSING_REASONS[judge_name].format(missing=missing),
    )


def score_with_judges(
    gap: GapEstimate | None,
    workflow: Workflow | None,
    case: EvalCase,
    graph: LearningGraph,
) -> list[JudgeResult]:
    """Run the three pinned judges over a (gap, workflow) pair. A missing
    artifact yields an honest 0.0 fail with a "[no artifact]" rationale — the
    judges themselves are never altered or skipped to make a mode look better."""
    # Judge 1: needs gap + workflow.
    if gap is not None and workflow is not None:
        j_gap = judge_gap_to_pedagogy(gap, workflow, graph)
    else:
        j_gap = _missing("gap_to_pedagogy", "diagnosis" if gap is None else "plan/lesson")

    # Judge 2: needs workflow + gap.target_concept_id (same call shape as runner.py).
    if workflow is not None and gap is not None:
        j_mod = judge_modality_fit(workflow, case.learner_model, gap.target_concept_id)
    else:
        j_mod = _missing("modality_fit", "plan/lesson" if workflow is None else "diagnosis")

    # Judge 3: needs gap.
    if gap is not None:
        j_prog = judge_adaptive_progression(gap, case.learner_model, case.expected_difficulty_band)
    else:
        j_prog = _missing("adaptive_progression", "diagnosis")

    return [j_gap, j_mod, j_prog]


# ---------------------------------------------------------------------------
# Observability — render a captured turn as a readable trace for error analysis
# (Hamel: "error analysis is the most important activity in evals"). Local files;
# no external service. LangSmith remains available behind the LANGSMITH_TRACING
# env var (src/llm.py) for anyone who wants the hosted UI.
# ---------------------------------------------------------------------------

def render_transcript(case: EvalCase, cap: AutonomousCapture, judges: list[JudgeResult] | None = None) -> str:
    """Human-readable trace of one agent turn: what it called, what it decided,
    what it taught, and (optionally) how the judges ruled."""
    L: list[str] = [f"# Trace — {case.case_id}", "", f"_{case.description}_", ""]
    L.append(f"Tool path: `{' -> '.join(cap.tool_sequence) or '(none)'}` · "
             f"cost ${cap.cost_usd:.4f}")
    L.append("")
    L.append("## What the agent did")
    L.append("")
    for ev in cap.events:
        e, p = ev["event"], ev["payload"]
        if e == "tool_call":
            L.append(f"- **calls** `{p.get('tool')}` {json.dumps(p.get('args', {}))[:160]}")
        elif e == "tool_result":
            mark = "ok" if p.get("ok") else f"ERROR: {p.get('error', '')}"
            L.append(f"  - result: {p.get('tool')} — {mark}")
        elif e == "gap":
            g = p.get("gap", {})
            L.append(f"  - diagnosis: target=`{g.get('target_concept_id')}` "
                     f"difficulty={g.get('suggested_difficulty')} — {g.get('rationale', '')[:200]}")
        elif e == "workflow":
            w = p.get("workflow", {})
            L.append(f"  - plan: modality=`{w.get('modality')}`, {len(w.get('steps', []))} steps")
        elif e == "artifact":
            s = p.get("step", {})
            L.append(f"  - **teaches** `{s.get('concept_id')}` / `{s.get('modality')}` "
                     f"(principle: {s.get('pedagogy_principle')})")
    if cap.final_text:
        L.append("")
        L.append(f"**Agent to learner:** {cap.final_text.strip()}")
    if judges:
        L.append("")
        L.append("## Judge verdicts")
        L.append("")
        for j in judges:
            L.append(f"- **{j.judge_name}**: `{j.verdict}` — {j.rationale}")
    L.append("")
    return "\n".join(L)


def write_trace(case: EvalCase, cap: AutonomousCapture, out_dir, judges: list[JudgeResult] | None = None, name: str | None = None) -> None:
    """Write <name>.md (readable) + <name>.json (full event stream) for a turn.
    `name` defaults to the case id; pass a per-trial name to avoid collisions."""
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = name or case.case_id
    (out / f"{stem}.md").write_text(render_transcript(case, cap, judges), encoding="utf-8")
    (out / f"{stem}.json").write_text(
        json.dumps({
            "case_id": case.case_id,
            "tool_sequence": cap.tool_sequence,
            "cost_usd": cap.cost_usd,
            "final_text": cap.final_text,
            "gap": cap.gap.model_dump(mode="json") if cap.gap else None,
            "teach_workflow": cap.teach_workflow.model_dump(mode="json") if cap.teach_workflow else None,
            "judges": [j.model_dump(mode="json") for j in judges] if judges else None,
            "events": cap.events,
        }, indent=2),
        encoding="utf-8",
    )
