# Worked example: `case_02_struggling_use_socratic`

The clearest demonstration of "modality adaptation" in the test suite. The learner's *stated* preference is reading, but they've already failed reading-based instruction twice on the target concept — so the agent overrides the preference and goes Socratic. The judges confirm this is the textbook-correct call.

Source files:
- Case input: [`evals/golden/case_02_struggling_use_socratic.json`](../evals/golden/case_02_struggling_use_socratic.json)
- Eval graph: [`evals/golden/graphs/cognitive_biases.json`](../evals/golden/graphs/cognitive_biases.json)
- Full results (all 6 cases): [`evals/results.md`](../evals/results.md), [`evals/results.json`](../evals/results.json)

---

## 1. Input: learner state

```json
{
  "user_id": "test_struggling",
  "domain_id": "cognitive_biases",
  "mastered_concepts": ["base_rate", "conditional_probability"],
  "struggling_concepts": ["base_rate_neglect"],
  "modality_preference": "reading",
  "difficulty_level": 3,
  "session_history": [
    {"concept_id": "base_rate_neglect", "modality": "reading", "correct": false, "notes": "got the medical-test problem wrong"},
    {"concept_id": "base_rate_neglect", "modality": "reading", "correct": false, "notes": "still missing the base rate"}
  ]
}
```

The key signals: prerequisites are mastered, the target concept is *struggling*, and the two failed turns were both reading-based.

---

## 2. ASSESS — `diagnose_learner` output

```json
{
  "target_concept_id": "base_rate_neglect",
  "rationale": "The learner is struggling with base_rate_neglect, but both its prerequisites (base_rate, conditional_probability) are already mastered. Per the rules, a struggling concept should be targeted directly when its prerequisites are mastered. No unresolved prerequisite gaps exist, so we focus on the struggling concept itself, easing the difficulty since the learner has failed it repeatedly.",
  "confidence": 0.85,
  "suggested_difficulty": 2,
  "prerequisite_gaps": []
}
```

Note the difficulty stepped *down* from 3 → 2: the agent's response to repeated failure is to reduce intrinsic load, not to push harder.

---

## 3. PLAN — `plan_workflow` output

**Primary modality: `socratic`.** The LLM's own rationale for the choice:

> *"The learner is struggling with base_rate_neglect and has failed twice on reading-based delivery of the medical-test problem, so re-reading is unlikely to help. Base rate neglect is a classic misconception-driven bias, and the graph hints socratic/interactive. A Socratic dialogue is chosen as the primary modality because it surfaces exactly WHY the learner drops the base rate rather than just restating the rule."*

The 5-step plan:

| # | Concept | Modality | Pedagogy principle | Objective |
|---|---|---|---|---|
| 1 | `base_rate` | reading | spaced_repetition | Re-activate the definition of base rates and why population frequency matters. |
| 2 | `conditional_probability` | reading | elaboration | Refresh how P(A\|B) combines a prior with evidence — sets up the medical-test scenario. |
| **3** | **`base_rate_neglect`** | **socratic** | **worked_example** | **Through guided questioning on a simplified medical-test problem, surface the learner's tendency to ignore the base rate.** |
| 4 | `representativeness_heuristic` | socratic | interleaving | Contrast with the representativeness heuristic — clarify why both lead to ignoring base rates. |
| 5 | `base_rate_neglect` | interactive | desirable_difficulty | Apply corrected reasoning to a fresh problem; retrieve the base rate first. |

Steps 1-2 reactivate already-mastered priors (spaced repetition is correct here — they were learned, not new). Step 3 is the **key teaching step** at the dropped difficulty. Step 4 interleaves the commonly-confused sister concept (Rohrer & Taylor 2007). Step 5 closes with a retrieval check (Bjork & Bjork 2011 — desirable difficulty).

---

## 4. GENERATE — the Socratic artifact for step 3

This is the actual output the learner sees. The "worked_example" principle plays out as a guided derivation rather than a told one.

**Title:** *The Surprising Math of a Positive Test*

**Opening:**
> Imagine a disease affects 1 in 1,000 people. A test for it is 99% accurate: if you have the disease it's positive 99% of the time, and if you don't have it it's positive only 1% of the time (false positives). You test positive. Let's reason through what your chance of actually having the disease really is.

**Dialogue script (6 agent turns, 6 learner prompts):**

| Speaker | Text |
|---|---|
| Agent | Before any calculation, what's your gut feeling: given a 99% accurate test came back positive, roughly what is the chance you have the disease? |
| Learner | *State your intuitive estimate and briefly why.* |
| Agent | Many people say about 99%, reasoning straight from the test's accuracy. But that ignores something. How many people in a town of 100,000 actually have this disease, given the 1-in-1,000 base rate? |
| Learner | *Compute the number of people who truly have the disease.* |
| Agent | Right — about 100 people. Now consider the 99,900 healthy people. The false-positive rate is 1%. How many of these healthy people will the test wrongly flag as positive? |
| Learner | *Calculate the number of false positives among the healthy group.* |
| Agent | So we have roughly 999 false positives. Of the 100 truly sick people, about 99 test positive. Out of everyone who tests positive, what fraction actually has the disease? |
| Learner | *Compute 99 divided by (99 + 999) and express it as a percentage.* |
| Agent | About 9%, not 99%. Your earlier gut estimate was off by a huge margin. What single piece of information did the intuitive 99% guess completely leave out? |
| Learner | *Name the information that was neglected and explain its effect.* |
| Agent | Exactly — the base rate. Because the disease is rare, the small pool of true cases gets swamped by false positives from the huge healthy majority. So how should the rarity of a condition change the way you read a single positive test? |
| Learner | *State the general lesson in your own words.* |

**Target insight (what the agent is steering toward):**
> When a condition is rare, even a highly accurate test yields a low probability of true illness after a positive result, because the base rate makes false positives from the large healthy population outnumber true positives — so ignoring the base rate (base rate neglect) leads to drastically overestimated probabilities.

The dialogue elicits the misconception (turn 1: "99% feels right"), forces the learner to compute the base-rate consequences themselves (turns 3, 5, 7), and only then names the bias. This is what re-reading the textbook definition couldn't do for this learner.

---

## 5. Judge scores

| Judge | Score | Why |
|---|---|---|
| `gap_to_pedagogy` | 0.70 | Target matches the gap; principles mostly appropriate; minor mislabel on step 3 (`worked_example` for a Socratic delivery) and a mild excursion to `representativeness_heuristic` on step 4 keep it from a perfect score. |
| `modality_fit` | **1.00** | "The target concept is in struggling_concepts and the learner failed twice on reading-based delivery — the precise signal favoring socratic over more reading. Base rate neglect is a classic misconception-driven bias, exactly where dialogue surfaces the underlying error." |
| `adaptive_progression` | **1.00** | "Suggested difficulty of 2 (level - 1) is appropriate to rebuild understanding given 0 correct recent turns, stays within [1, 5], and falls inside the expected band (2, 3)." |

**Verdict: PASS.** The two judges that gate the differentiator — modality routing and difficulty adaptation — both scored 1.0 with rationale that explicitly cites the learner-state signals that drove the decision. This is the auditable evidence the eval harness exists to produce.

---

## Why this case matters

Existing edtech (Squirrel AI, Khanmigo, Adaptemy) routes content by topic or by correct/incorrect feedback. None of them route by *medium*. This case is the smallest concrete demonstration of medium-routing working:

1. The learner *said* they preferred reading.
2. Reading *had been tried* on this specific concept.
3. Reading *had failed*, twice.
4. The agent detected the conflict between stated preference and observed outcome, **overrode the preference**, picked a modality known to surface the relevant misconception, and explained its reasoning in the workflow rationale.
5. An independent judge confirmed the call was correct, citing the same signals the agent did.

That's the loop the eval harness exists to validate at scale.
