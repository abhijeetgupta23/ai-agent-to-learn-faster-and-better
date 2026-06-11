# How it works

No framework, no hidden agent runtime. The system is a sequence of typed Python
function calls, five of which happen to ask Claude a question. This document
walks through one real request end-to-end so you can see exactly what happens at
each step — including the model's actual reasoning, captured live.

If you want to skip the prose: run `python run_evals.py --trace docs/traces`
and read the generated `docs/traces/*.md`. Every LLM decision in the system is
in there — the prompt sent, the model's summarized reasoning, and the parsed
output.

---

## The mental model

A teaching session is one loop: **ASSESS → PLAN → GENERATE → OBSERVE → ADAPT.**
Four of the five steps are deterministic Python; the intelligence is concentrated
in three LLM calls (diagnose, plan, generate). Everything the LLM returns is
parsed into a Pydantic model and validated — if the model returns malformed JSON
or references a concept that isn't in the graph, the call raises immediately
rather than corrupting state.

```
diagnose_learner ──▶ plan_workflow ──▶ generate_artifact ──▶ (learner responds) ──▶ update_learner_model
   LLM call             LLM call           LLM call              plain Python            plain Python
   GapEstimate          Workflow           Artifact              SessionTurn             LearnerModel
```

That's the whole machine. There is no orchestration layer making hidden
decisions — these five functions, called in order, are the agent.

---

## Where the intelligence is (and isn't)

| Step | Who decides | What's deterministic |
|---|---|---|
| ASSESS (`diagnose_learner`) | **LLM** picks the target concept + difficulty | The result is validated against the graph — a target not in the graph is rejected |
| PLAN (`plan_workflow`) | **LLM** authors the 3-5 step sequence + picks the modality | Step count (3-5) and concept-id existence are enforced in code |
| GENERATE (`generate_artifact`) | **LLM** writes the actual lesson | The modality → schema mapping is fixed; output is schema-validated |
| OBSERVE | — | Pure Python: capture the learner's correct/incorrect + notes |
| ADAPT (`update_learner_model`) | — | Pure Python: difficulty clamp `[1,5]`, mastery/struggle bookkeeping, modality-preference slide |

The LLM never touches difficulty clamping or learner-model bookkeeping — those
are deterministic guardrails in `src/tools/update.py`. The LLM's judgment is
fenced into three well-defined decisions, each with a typed contract.

---

## A real request, call by call

Below is the actual trace of `case_02_struggling_use_socratic` — a learner who
has mastered the prerequisites for *base rate neglect* but failed it twice on
reading-based delivery. Full trace: [`traces/case_02_struggling_use_socratic.md`](traces/case_02_struggling_use_socratic.md).

The reasoning quotes below are the model's own summarized thinking, captured by
the trace layer — not paraphrases.

### Call 1 — `diagnose` (6.9s, 2,631 in / 498 out)

**The model reasoned:**
> The learner has mastered the prerequisites for base_rate_neglect, so I'm focusing on that struggling concept. They've failed twice, which makes me consider dropping the difficulty from 3 to 2, though the rule about multiple struggling concepts doesn't quite apply here since there's only one.

**It produced:** `target_concept_id: base_rate_neglect`, `suggested_difficulty: 3`, `confidence: 0.85`.

Notice the reasoning is *visibly weighing a rule* ("the multiple-struggling rule doesn't quite apply here since there's only one") — this is the kind of judgment that the one-line `rationale` field alone would hide. You can see it decide.

### Call 2 — `plan` (13.9s, longest call — it's authoring a curriculum)

**The model reasoned:**
> The learner's struggling with base rate neglect after two attempts, so I need to shift to a socratic approach. I'll start by activating what they already know about base rates and spaced repetition, then work through a conditional probability example to build understanding. The key is weaving in the representativeness heuristic to show how it conflicts with base rate thinking, then practice with appropriately challenging problems.

**It produced:** a 5-step workflow with primary modality `socratic`. The "shift to a socratic approach" is the differentiator decision — and you can read the *reason* it shifted (two failed attempts), which is exactly what the `modality_fit` judge later scores.

### Call 3 — `generate:reading` (13.7s)

**The model reasoned:** _(nothing — thinking was skipped)_

This is adaptive thinking working as intended: writing a reading passage is a
generation task, not a reasoning task, so the model spent no thinking tokens on
it. The trace shows `(none)` honestly rather than fabricating reasoning. Compare
to the diagnose/plan calls, where the model thought before deciding. **You can
tell, per call, whether the model deliberated or just produced.**

### Calls 4-6 — the three judges

Each judge is itself an LLM call with its own captured reasoning. The
`adaptive_progression` judge, for example:

> The learner has one struggling concept at difficulty 3, which doesn't warrant a step down, and with only 2 recent turns and no correct answers, there's no streak to trigger a step up. The suggested difficulty of 3 aligns perfectly with their current level... Though the zero correct answers might suggest stepping down could help, the principle here is to keep them at their current difficulty level.

The judge is reasoning through the *same rules* the diagnoser used, independently,
and arriving at "3 is correct." That's the audit: two separate LLM calls, both
shown their reasoning, agreeing on the difficulty with cited rules.

---

## "But the evals are an LLM grading an LLM"

Correct — and the trace is the answer to that concern. You don't have to trust
the score; you can read the judge's reasoning and the rules it applied, then
check that reasoning against the deterministic facts in the prompt (which the
trace also captures, under the collapsible "prompt sent" block). If a judge's
reasoning doesn't match its score, you'll see it.

The judge prompts also include hard, checkable signals computed in Python before
the call — e.g. `modality_fit` is told `is_struggling_with_target: true/false`
(a set-membership check, not an LLM opinion), and `adaptive_progression` is told
whether the suggested difficulty is `in_band` (an arithmetic check). The LLM
weighs edge cases; the booleans it weighs are deterministic.

---

## How to see any of this yourself

```bash
# Full reasoning trace for every golden case
python run_evals.py --trace docs/traces

# Then read any case's trace
cat docs/traces/case_02_struggling_use_socratic.md
```

Each trace `.md` has, per LLM call: the model's summarized reasoning, the parsed
output, and a collapsible block with the exact prompt sent. The `.json` sibling
has the same data unabridged for programmatic inspection.

### The one switch

Reasoning visibility is controlled by `src/llm.py`:

```python
THINKING_ENABLED = os.environ.get("ADAPTIVE_LEARNING_THINKING", "on") != "off"
_THINKING = {"type": "adaptive", "display": "summarized"}  # the visible-reasoning switch
```

Adaptive thinking lets the model decide *per call* how much to reason;
`display: "summarized"` is what makes that reasoning come back to us instead of
staying hidden server-side. Set `ADAPTIVE_LEARNING_THINKING=off` to disable it
(faster and cheaper, but opaque — and the traces go quiet).

---

## Run-to-run variation is real and visible

These are LLM calls, so two runs of the same case can differ. In one earlier run
the diagnoser dropped difficulty 3 → 2 for this case; in the traced run above it
held at 3. Both are defensible (the learner has exactly one struggling concept,
which sits on the boundary of the step-down rule), and the eval harness scores
both as passing because the expected band is `[2, 3]`. The trace makes this
non-determinism legible: you can see *why* a given run chose what it chose,
rather than being surprised by a different number with no explanation. That's the
difference between a black box and an auditable one.
