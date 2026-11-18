# Learn Faster: agent architecture

Final design as of 17 Nov 2026. Not built yet. Companion doc: `learn-faster-product.md`.
Repo baseline: `abhijeetgupta23/ai-agent-to-learn-faster-and-better` at commit `df69fd3` (9 Nov 2026).

Give this file to Claude Code as the brief. Build order: section 12. Open decisions: section 10.

## 1. Principle

The model decides. Code guarantees.

- The model picks every move.
- Code runs the checks, enforces the gates and logs everything. It cannot be argued with.
- New edge cases become evals, not new branches.

Learner assumptions (v1):
- She already codes. Not a beginner course.
- AI coding tools are allowed. The tutor tests ownership: she made the design call and can explain, change and debug what she built.
- The project grows one piece at a time, so no single prompt builds it.
- Tutor help counts against "built alone". Her own AI tool use does not.

Course packs:
- The loop, moves, gates and recall are domain-agnostic. Everything specific to a subject lives in a course pack: the context graph, the project and its pieces with briefs, the check pack (tests, rule checks, judge rubric), and ownership-check prompts.
- Submissions are generic artifacts (code now; emails, scripts or role-play transcripts in later domains). Checks plug in per pack.
- Only the coding pack (building AI agents) gets built now. Non-tech domains (for example sales, with simulated buyers as the test suite) come later.
- Done = the project works: it passes the pack's final acceptance test, and she owns it (demo plus a change request).

## 2. The loop

```
learner submits work
  -> CODE runs the checks (always, no model)          e.g. "9 of 15 pass" (5 questions x 3 runs)
  -> MODEL reads: attempt + check results + learner record + concept map
     returns ONE move from the fixed list
  -> CODE checks the move against the gates
       blocked -> reason returned to the model, it picks again
       passes  -> move runs
  -> CODE logs the move (and to the help ledger if it is help)
  -> result reaches the learner
```

Model output contract (one per turn):

```json
{ "move": "hint", "concept_id": "tool_description", "content": "...", "reason": "..." }
```

## 3. Moves (11)

| Group | Move | Rule |
|---|---|---|
| Ask, assign | `ask` | Find what she knows or where she is stuck |
| | `ownership_check` | Ask her to explain a line, make a small change, or fix a bug in her own code. Not help. |
| | `set_task` | Must include a brief: `why`, `done_looks_like`, `you_start_with`. Never how. |
| Teach | `explain` | Allowed before a task if the idea is new to her |
| | `example` | Same |
| | `hint` | Gate 1 |
| | `fix` | Gate 1 |
| Record | `note` | Saves an observation |
| | `built_alone` | Gate 2 |
| | `show_progress` | Gate 3 |
| | `confirm_mastery` | Gate 4 |

`explain`, `example`, `hint` and `fix` are help and go in the help ledger. `ownership_check` is not help.
Reading the attempt and running checks are not moves. Code does both on every submission.

## 4. Gates

```python
def gate_1(move, s):   # attempt before hint or fix
    if move in ("hint", "fix"):
        return s.attempts_on_current_task > 0

def gate_2(move, s):   # built alone
    if move == "built_alone":
        return (s.help_since_last_attempt == 0
                and s.last_check.passed == s.last_check.total
                and s.static_method_ok and s.judge_method_ok
                and s.ownership_check_passed)   # AI tools allowed; she must own it

def gate_3(s):         # before session close
    return s.progress_shown

def gate_4(move, s, concept):   # mastery
    if move == "confirm_mastery":
        use = s.latest_use(concept)
        return (use.unaided            # no tutor help; her AI tools allowed
                and use.ownership_check_passed
                and use.gap_days >= REAL_GAP_DAYS
                and use.session_id != concept.first_learned_session)
```

A miss is never scored down. A blocked move returns its reason to the model.

## 5. Checks and judge

- Check runner (code): run the learner's agent against fixed test questions, several runs each. Report `passed / total` plus failures.
- Static read (code): detect known wrong methods, e.g. `if "refund" in question:` in place of a tool description.
- Judge (separate model): checks method where code cannot. The acting model never grades itself.

## 6. Recall and mastery (locked)

- Need-driven. The concept map says what today's piece builds on. Those concepts come back inside today's task. No dates, no fixed schedule, no minimum gap.
- Mastery = one unaided success after a real gap (days). Same-session reuse is practice.
- Maximum-gap fallback for must-know concepts nothing has needed: first, the model shapes the next task to need it; otherwise a warm-up item (max three per session, model picks). Other concepts retire.
- Placeholders: `MAX_GAP_DAYS = 14`; a missed concept comes back sooner. Must-know = anything two or more later pieces build on.
- Later metrics: false mastery rate (confirmed, later needed help) and wasted recall rate (passed with ease, gap too short).

## 7. Data model

| Entity | Fields |
|---|---|
| `Learner` | id, prior_knowledge (by concept), current_course, current_piece |
| `Concept` | id, course, builds_on[], must_know, first_learned_session |
| `Task` | id, piece, concept_ids[], brief {why, done_looks_like, you_start_with} |
| `Submission` | id, task_id, learner_id, artifact (code now), artifact_type, ts |
| `OwnershipCheck` | submission_id, kind (explain/change/fix), passed, ts |
| `CheckRun` | submission_id, passed, total, failures[], static_flags[] |
| `JudgeVerdict` | submission_id, method_ok, notes, model |
| `MoveLog` | session_id, move, concept_id, gate, allowed, reason, ts, tokens, cost |
| `HelpLedger` | session_id, task_id, kind (explain/example/hint/fix), ts |
| `ConceptUse` | learner_id, concept_id, session_id, gap_days, help_used, unaided, ts |
| `MasteryEvent` | learner_id, concept_id, confirmed, ts |

Log every `ConceptUse`, gate 4 decision and retirement from day one.

## 8. Repos

Rule: anything that is not a moat is public. The method is public; data and tuned values are private.

| Public (core package, GitHub) | Private (imports core; the site deploys from here) |
|---|---|
| Loop, moves, all four gates | Context graphs per domain and full course spines (the moat) |
| Check runner, static read, judge | Tuned values (gaps, thresholds) |
| Move log, help ledger, trace view | Eval sets from real learner sessions |
| Eval harness + edge-case evals | Learner data |
| Head-to-head benchmark | Company layer (courses from docs, team report, admin) |
| Cost per session | Billing, freemium caps, sign-in |
| Sample project (2 pieces) | |

`src/graph/` and `evals/golden/graphs` are already public under MIT. New graph data and course spines start in the private repo and are never pushed to the public one.

## 9. Changes from today's repo

| Area | Today | Change |
|---|---|---|
| Control | `src/agent/autonomous.py`: model calls tools freely (diagnose, plan_lessons, teach, record_observation, view_learner) | One move per turn from the fixed list; code validates and runs it |
| Mastery | `src/tools/update.py`: one correct answer appends to `mastered_concepts` | Gate 4 only |
| Recall | Spacing fields in `src/schemas.py` unused | Need-driven recall, `ConceptUse` logging |
| Personalising | `modality_preference` | Remove; use prior knowledge |
| Help | Not recorded | `HelpLedger` |
| Checks | None on learner code | Check runner + static read |
| Evals | 3 judges, 6 golden cases (`evals/golden/`) | Add edge-case evals (section 11) |
| Benchmark | `run_compare.py` / `evals/compare.py`: workflow vs autonomous | Add plain Claude and plain GPT baselines |

Reuse: `src/harness/`, `src/trace.py`, `evals/`.

## 10. Open technical decisions

| # | Decision | Recommended |
|---|---|---|
| 1 | How work reaches the agent | Decided for v1: she submits her code (paste or repo link). AI tools allowed. No AI-log analysis in v1 |
| 2 | Live chat or submission-based | Open |
| 3 | Models for tutor, checks, judge | Open; cheaper models for checks and judge |
| 4 | Real gap, max gap, must-know list | Start at 14 days; tune from logs |
| 5 | Repos | Keep current repo as public core; new private repo |

## 11. Evals

Scripted learners, each with a pass condition:

1. Pushes for the answer before trying: no hint or fix.
2. Right result, wrong method: not built alone.
2b. Piece built with AI, she can't explain or change it: not built alone.
2c. Piece built with AI, she explains it and makes a requested change: built alone.
3. Hint given, then a passing solution: not built alone.
4. Brand-new idea (MCP), no prior knowledge: explain and example before the task.
5. Already knows the idea: no explain or example before the task.
6. Same-session reuse: mastery not confirmed.
7. Unaided use 5 days later: mastery confirmed.
8. Must-know concept near the max gap: next task needs it, or a warm-up appears.
9. Prompt-leak attempt: no rules leak.
10. Off-topic chatbot use: redirected.

Head-to-head benchmark vs plain Claude and plain GPT. Publish the scripts and scores:
- Holds the answer when pushed.
- Catches right result, wrong method.
- Feedback matches the check results.

## 12. Build order

Ordered by dependency. Each step ends with a commit. Record every eval score and failure count in `docs/baseline.md` (Phase 1) and `docs/scores.md` (after).

Phase 1: foundations (one session)
1. Baseline: run current tests and evals; save scores to `docs/baseline.md`.
2. Data model (section 7) and course-pack format. Coding pack with the 2-piece sample project (order-status tool, then refund tool), its tests and a reference solution. Stop for schema review.
3. Check runner (passed/total + failures, several runs each) and static read (flags `if "refund" in question:` routing).
4. Scripted-learner eval harness for section 11. Most evals fail until Phase 2. Record the failures.

Phase 2: the loop
5. Move contract and loop rewrite in `autonomous.py`: one validated move per turn; move log.
6. Help ledger, gate 1, gate 3.
7. `ownership_check`, judge model, gate 2.
8. Trace view and cost per session.
9. Same-session evals green: 1 to 5, 9, 10.

Phase 3: public-ready
10. Head-to-head benchmark vs plain Claude and plain GPT.
11. Split repos: public core, new private repo imports it. Nothing private exists before this step.

Phase 4: private product
12. Full course spine and context graph for course 1.
13. ConceptUse logging, need-driven recall, max-gap fallback, gate 4. Simulated clock for multi-day evals. Evals 6 to 8 green.
14. Sign-in, rate limits, freemium caps; deploy from the private repo.
15. Later: company layer.

## 13. Production guardrails

- Rules live in code, never only in the prompt.
- Logic on the server; nothing sensitive reaches the browser.
- Sign-in and rate limits; per-user daily cap.
- Cost per session tracked from the first run.
