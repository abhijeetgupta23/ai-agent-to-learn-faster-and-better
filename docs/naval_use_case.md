# Use case: the seven Naval disciplines

> *"Study microeconomics, game theory, psychology, persuasion, ethics, mathematics, and computers."* — Naval Ravikant

This is exactly the use case the agent is built for: a self-learner trying to absorb seven foundational disciplines faster than the tooling around them changes. Each domain has different prerequisite depth, different misconception profiles, and rewards a different teaching medium — so the same agent has to make seven different sets of routing decisions on the same learner.

The seven domains ship as Markdown files in [`domains/`](../domains/):

| Domain | Source | Best modality (typical) | Why |
|---|---|---|---|
| Microeconomics | [`microeconomics.md`](../domains/microeconomics.md) | reading + interactive | Conceptual + worked examples (elasticity, equilibrium) |
| Game theory | [`game_theory.md`](../domains/game_theory.md) | interactive | Solve games, then read theory |
| Psychology | [`psychology.md`](../domains/psychology.md) | mixed — Socratic for biases | Many concepts ARE misconceptions |
| Persuasion | [`persuasion.md`](../domains/persuasion.md) | interactive (scenarios) | Applied skill, not theory |
| Ethics | [`ethics.md`](../domains/ethics.md) | Socratic | Tradeoffs surface in dialogue |
| Mathematics | [`mathematics.md`](../domains/mathematics.md) | interactive (retrieval practice) | Bjork & Bjork desirable difficulty |
| Computers | [`computers.md`](../domains/computers.md) | reading + interactive | Abstraction stack + practice |

The agent doesn't take the table above as input — it works the modality out for itself from each generated graph and from the learner's state. This file traces it doing exactly that across two of the seven.

## The traced learner

**Alice** has been reading psychology for a week. She has internalized the dual-process model (System 1 / System 2) but failed twice on the *fundamental attribution error* — both attempts were reading-based. She's never opened the persuasion material. She has a stated preference for reading.

Both sessions ran with `scripts/naval_demo.py`. The full trace is at [`naval_use_case_trace.json`](naval_use_case_trace.json) — what follows is the readable version.

---

## Session A — Psychology

### The extracted graph (8 concepts, 9 edges)

The graph extractor produced these concept IDs from `psychology.md`:

```
dual_process_model, cognitive_bias_concept, fundamental_attribution_error,
confirmation_bias, cognitive_dissonance, hedonic_adaptation, loss_aversion,
social_proof
```

Two `interleave_with` edges appeared, both well-motivated:
- `confirmation_bias ↔ cognitive_dissonance` — students often conflate "rejecting evidence" with "feeling discomfort from contradiction"
- `loss_aversion ↔ hedonic_adaptation` — both modulate how we feel about gains/losses over time

Notice the graph introduced an **intermediate concept** I didn't seed: `cognitive_bias_concept`. The LLM correctly judged that "what a cognitive bias is" deserves its own node before any specific bias (FAE, confirmation, etc.) — it's the genus of which the specific biases are species. This matters in the next step.

### What `diagnose_learner` decided

```
target_concept_id: cognitive_bias_concept   ← NOT fundamental_attribution_error
confidence: high
suggested_difficulty: down-shifted
```

The agent's rationale (verbatim):

> *"The learner is struggling with fundamental_attribution_error, but its prerequisite cognitive_bias_concept is not yet mastered. Per the rules, we must resolve the deepest unresolved prerequisite first."*

**This is the case_06 behavior playing out live.** I designed the demo expecting a "struggling → Socratic override" trace (like case_02). What the agent actually did was more correct: it noticed Alice was failing FAE because she didn't have the umbrella concept (*what is a bias?*) and **backfilled the prerequisite first**. A pure modality swap on FAE wouldn't have fixed the underlying gap.

### What `plan_workflow` produced

| # | Concept | Modality | Pedagogy principle |
|---|---|---|---|
| 1 | dual_process_model | socratic | spaced_repetition (reactivate the mastered prior) |
| 2 | cognitive_bias_concept | reading | elaboration |
| 3 | cognitive_bias_concept | reading | worked_example |
| 4 | cognitive_bias_concept | interactive | desirable_difficulty |

Modality is `reading` for the key teaching steps. The rationale, in part:

> *"The target concept is a prerequisite the learner has not yet seen and is expository foundational material; the node's only modality hint is 'reading' and the learner's modality_preference is reading, so the KEY teaching steps (2 and 3) use reading. Although the downstream concept (FAE) is in struggling_concepts, the immediate gap is prerequisite knowledge, not a misconception about bias — so Socratic is not warranted yet."*

Note the agent reactivates `dual_process_model` (already mastered) using `spaced_repetition` — exactly the right principle for previously-mastered knowledge, and exactly the wrong principle for brand-new content. This is the kind of grounded routing the eval `gap_to_pedagogy` judge scores for.

### Excerpt from the generated reading artifact

Title: ***Cognitive Bias: When Mental Shortcuts Mislead Us***

> Your brain handles thinking in two modes. System 1 is fast, automatic, and effortless — it lets you read a word or sense a friend's mood without trying. System 2 is slow, deliberate, and effortful — it kicks in when you multiply 17 × 24 or weigh a big decision. Most of the time, System 1 serves us well. But it gets us into trouble when it confidently answers a question that actually requires System 2.
>
> A cognitive bias is a systematic, predictable deviation from rational judgment. Two words deserve emphasis. **'Systematic'** means the error isn't random noise — it leans in a consistent direction, like a scale that always reads two pounds heavy. **'Predictable'** means researchers can reliably reproduce the same mistake across many people. Because biases are patterned, we can anticipate and sometimes correct for them.

The opening *explicitly bridges* to what Alice already mastered (System 1/2) before introducing the new concept. That's elaboration as a pedagogy principle, executed correctly — the agent doesn't just say "elaboration" in the step metadata, it actually elaborates from the known to the new.

Key takeaways extracted by the agent:
- Systematic + predictable = bias (not random error)
- Biases arise when System 1 answers a System-2 question
- Knowing about a bias doesn't auto-prevent it (signals when to slow down)
- This is the foundation for understanding specific named biases (anchoring, availability, confirmation, …)

The last takeaway is the bridge to FAE — Alice's struggling concept. The agent is laying the ground for the *next* session to land FAE successfully.

---

## Session B — Persuasion

### The extracted graph (10 concepts, 18 edges — far denser than psychology)

```
persuasion_overview, reciprocity, commitment_consistency, social_proof,
liking, authority, loss_aversion, scarcity, framing, ethical_line
```

Three `interleave_with` edges:
- `social_proof ↔ authority` (both lean on external validation)
- `reciprocity ↔ commitment_consistency` (both exploit self-image)
- `scarcity ↔ framing` (both manipulate perceived loss)

This graph is structurally different from psychology's: persuasion has a single root concept (`persuasion_overview`) and 7+ techniques branching off it, vs. psychology's tree of biases with several parallel root concepts. **Same agent, same prompts — different graph shapes emerge from the source material.**

### What `diagnose_learner` decided

```
target_concept_id: persuasion_overview
suggested_difficulty: 1
```

Rationale: *"The learner has no mastered concepts and no history. 'What Persuasion Is' is the only concept with no prerequisites and the lowest difficulty, serving as the root for all other concepts. It must be mastered before any branch."*

This is the case_01 behavior — clean novice start.

### What `plan_workflow` produced

| # | Concept | Modality | Pedagogy principle |
|---|---|---|---|
| 1 | persuasion_overview | reading | elaboration |
| 2 | persuasion_overview | reading | elaboration |
| 3 | persuasion_overview | interactive | desirable_difficulty |
| 4 | persuasion_overview | interactive | desirable_difficulty |

Reading for the introduction (steps 1–2), then interactive retrieval practice (3–4). No Socratic — there's no misconception to surface for a brand-new concept.

### Excerpt from the generated reading artifact

Title: ***What Persuasion Really Is***

> Every day, people try to change your mind. A friend suggests a restaurant, an ad promises a better life, a coworker asks for a favor. Sometimes you say yes, sometimes no. Persuasion is the art and science behind those moments. Put simply, persuasion is the use of psychological levers to influence what people believe and what they do.
>
> Think of a lever the way you would in the physical world. A lever lets you move a heavy rock with a small push, as long as you place it in the right spot. Psychological levers work the same way. With a small, well-placed nudge, you can shift someone's beliefs or actions far more than you could by simply shouting your opinion louder. The trick is knowing where the levers are.

The first takeaway: *"Persuasion is the use of psychological levers to influence what people believe and do."* The third: *"Robert Cialdini studied real-world influence and catalogued the major principles as reliable shortcuts."* The agent already knows step 3+ will introduce those Cialdini principles — it's positioning for them.

---

## What this trace proves

1. **Same agent, two domains, two different curricula.** Psychology session has 4 steps focused on backfilling a prerequisite; persuasion has 4 steps introducing a root concept. The agent doesn't have domain-specific code paths — both decisions fell out of the same `diagnose_learner` and `plan_workflow` calls on different graphs and different learner states.
2. **Graph shape varies with the source.** Psychology produced a flat tree with 9 edges; persuasion produced a tight hub-and-spoke with 18 edges, half of them direct from the root. The extractor isn't using a template.
3. **The right tool for the right state.** The psychology session triggered a *prerequisite backfill* (case_06 in the eval suite). The persuasion session triggered a *novice start* (case_01). These are two of the six adaptation patterns the eval harness scores — and they showed up in two of the seven Naval domains without being asked.
4. **Modality routing is conservative and correct.** Neither session went Socratic, because neither learner had a *known misconception of the target concept*. The agent only reaches for Socratic when the evidence warrants it — exactly what `case_02_struggling_use_socratic` in the eval suite proves and what the FAE-driven case in psychology will likely trigger on Alice's *next* session, once the prerequisite is mastered.

---

## Scored verdict

The two sessions above aren't just asserted to be correct — they're run through
the same three judges as the golden eval suite (`scripts/evaluate_naval.py`,
full output in [`naval_eval_results.md`](naval_eval_results.md)):

| Session | gap_to_pedagogy | modality_fit | adaptive_progression | Pass |
|---------|-----------------|--------------|----------------------|------|
| psychology | 1.00 | 1.00 | 1.00 | OK |
| persuasion | 1.00 | 1.00 | 1.00 | OK |

Both score 1.00 on every judge. The judges independently confirmed the claims
this trace makes by prose: the psychology session correctly backfills the
un-introduced prerequisite (rather than swapping FAE's modality), reserves
`spaced_repetition` for the *mastered* prior while using `elaboration` /
`worked_example` for the new concept, and steps difficulty down to 2 for a
struggling learner; the persuasion session opens a novice on the root concept
with reading + retrieval practice at difficulty 1, with no unwarranted Socratic.

---

## What's still missing (the honest scope note)

`loss_aversion` appears as a node in **both** the psychology graph and the persuasion graph. The natural next step is cross-domain interleaving — when Alice masters `loss_aversion` in psychology, the persuasion session for `scarcity` should automatically reference it as a prior, even though they live in separate graphs.

The current `LearnerModel` is scoped to one `domain_id`, so V1 doesn't do this yet. The extension is small:
- Merge graphs at session start, deduplicating nodes by name
- Or: let `diagnose_learner` accept a list of graphs and resolve interleave_with edges across them

That's the natural V2. It's deliberately out of scope here — V1 is about proving the per-domain loop, with an eval harness to back it.
