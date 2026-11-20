# Learn Faster: agent architecture

Final design as of 17 Nov 2026. Not built yet. (The product doc is kept private.)
Repo baseline: `abhijeetgupta23/ai-agent-to-learn-faster-and-better` at commit `df69fd3` (9 Nov 2026).

Names follow `docs/GLOSSARY.md`. Give this file to Claude Code as the brief. Build order: section 12. Open decisions: section 10.

## 1. Principle

The model decides. Code guarantees.

- The model picks every move. That is where personalisation and flexibility come from; code can't adapt like that.
- Code runs the checks, enforces the gates and logs everything. It cannot be argued with.
- New edge cases become evals, not new branches.

Learner assumptions (v1):
- She already codes. Not a beginner course.
- AI coding tools are allowed. The tutor tests ownership: she made the design call and can explain, change and debug what she built.
- The project grows one milestone at a time, so no single prompt builds it.
- Tutor help counts against "built alone". Her own AI tool use does not.

Courses:
- The loop, tutor moves, gates and recall are domain-agnostic. Everything specific to a subject lives in a course: the skills (with `needs`), the project and its milestones with briefs, the tests, the `method_questions` (asked to Jev), the `judge_rubric` and `walkthrough_questions`.
- Submissions are generic artifacts (code now; emails, scripts or role-play transcripts in later domains). Checks plug in per course.
- Only the coding course (building AI agents) gets built now. Non-tech domains (for example sales, with simulated buyers as the test suite) come later.
- Done = the project works: it passes the course's final acceptance test, and she owns it (demo plus a change request).

## 2. The loop

```
learner submits work
  -> CODE runs the tests (always, no model) and asks Jev the method questions          e.g. "9 of 15 pass" (5 questions x 3 runs)
  -> MODEL reads: attempt + test results + learner record + skill map
     returns ONE tutor move from the fixed list
  -> CODE checks the move against the four gates
       blocked -> reason returned to the model, it picks again
       passes  -> move runs
  -> CODE logs the move in TutorMoveLog (and in TutorHelpLog if it is help)
  -> result reaches the learner
```

Model output contract (one per turn):

```json
{ "move": "hint", "skill_id": "tool_description", "content": "...", "reason": "..." }
```

## 3. Tutor moves (11)

| Group | Move | Rule |
|---|---|---|
| Ask, assign | `ask` | Find what she knows or where she is stuck |
| | `walkthrough_check` | Ask her to explain a line, make a small change, or fix a bug in her own code. Not help. |
| | `set_task` | Must include a brief: `why`, `done_looks_like`, `you_start_with`. Never how. |
| Teach | `explain` | Allowed before a task if the idea is new to her |
| | `example` | Same |
| | `hint` | `try_first_gate` |
| | `fix` | `try_first_gate` |
| Record | `note` | Saves an observation |
| | `built_alone` | `built_alone_gate` |
| | `show_progress` | `progress_gate` |
| | `confirm_mastery` | `mastery_gate` |

`explain`, `example`, `hint` and `fix` are help and go in `TutorHelpLog`. `walkthrough_check` is not help.
Reading the attempt and running tests are not moves. Code does both on every submission.

## 4. Gates

```python
def try_first_gate(move, s):   # attempt before hint or fix
    if move in ("hint", "fix"):
        return s.attempts_on_current_task > 0

def built_alone_gate(move, s):   # built alone
    if move == "built_alone":
        return (s.help_since_last_attempt == 0
                and s.last_test_result.passed == s.last_test_result.total
                and s.judge_method_ok
                and s.walkthrough_passed)   # AI tools allowed; she must own it

def progress_gate(s):         # before session close
    return s.progress_shown

def mastery_gate(move, s, skill):   # mastery
    if move == "confirm_mastery":
        use = s.latest_use(skill)
        return (use.unaided            # no tutor help; her AI tools allowed
                and use.walkthrough_passed
                and use.gap_days >= REAL_GAP_DAYS
                and use.session_id != skill.first_learned_session)
```

A miss is never scored down. A blocked move returns its reason to the model.

## 5. Tests and judge

- Test runner (code): run the learner's agent against fixed test questions, several runs each. Report a `TestResult`: `passed / total` plus `failures`.
- Method check (Jev): detect known wrong methods by asking Jev yes/no method questions listed in each milestone's `method_questions`, e.g. "does it route by matching the word 'refund' in the question?". Answers above the threshold become `JudgeIssue`s in a `JudgeReview`. Replaces the red-flag rules/scan (owner decision 2026-11-20); same meaning, a calibrated model reads the code instead of regex.
- Judge (separate model): reviews method where code cannot, against the course's `judge_rubric`; returns a `JudgeReview`. The acting model never grades itself.

## 6. Recall and mastery (locked)

- Need-driven. `needs` says what today's milestone builds on. Those skills come back inside today's task. No dates, no fixed schedule, no minimum gap.
- Mastery = one unaided success after a real gap (days). Same-session reuse is practice.
- Maximum-gap fallback for must-know skills nothing has needed: first, the model shapes the next task to need it; otherwise a warm-up item (max three per session, model picks). Other skills retire.
- Placeholders: `MAX_GAP_DAYS = 14`; a missed skill comes back sooner. Must-know = anything two or more later milestones need.
- Later metrics: false mastery rate (confirmed, later needed help) and wasted recall rate (passed with ease, gap too short).

## 7. Data model

Python classes are CamelCase; stored fields are snake_case. Code: `src/schemas.py`. `TestResult.failures` is a list of failures for now.

| Entity | Fields |
|---|---|
| `Learner` | id, prior_knowledge (by skill), current_course, current_milestone |
| `Skill` | id, course, needs[], must_know, first_learned_session |
| `Task` | id, milestone, skill_ids[], brief {why, done_looks_like, you_start_with} |
| `Submission` | id, task_id, learner_id, content, content_type (code now), ts |
| `WalkthroughCheck` | submission_id, kind (explain/change/fix), passed, ts |
| `TestResult` | submission_id, passed, total, failures[] |
| `JudgeReview` | submission_id, method_ok, notes, model |
| `TutorMoveLog` | session_id, move, skill_id, gate, allowed, reason, ts, tokens, cost_usd |
| `TutorHelpLog` | session_id, task_id, kind (explain/example/hint/fix), ts |
| `SkillUseLog` | learner_id, skill_id, session_id, gap_days, help_used, unaided, ts |
| `MasteryLog` | learner_id, skill_id, confirmed, ts |

Log every `SkillUseLog`, `mastery_gate` decision and retirement from day one.

## 8. Repos

Rule: anything that is not a moat is public. The method is public; data and tuned values are private.

| Public (core package, GitHub) | Private (imports core; the site deploys from here) |
|---|---|
| Loop, moves, all four gates | Context graphs per domain and full course spines (the moat) |
| Test runner, method check, judge | Tuned values (gaps, thresholds) |
| `TutorMoveLog`, `TutorHelpLog`, trace view | Eval sets from real learner sessions |
| Eval harness + edge-case evals | Learner data |
| Head-to-head benchmark | Company layer (courses from docs, team report, admin) |
| Cost per session | Billing, freemium caps, sign-in |
| Sample course (2 milestones) | |

`src/graph/` and `evals/golden/graphs` are already public under MIT. New graph data and course spines start in the private repo and are never pushed to the public one.

## 9. Changes from today's repo

| Area | Today | Change |
|---|---|---|
| Control | `src/agent/autonomous.py`: model calls tools freely (diagnose, plan_lessons, teach, record_observation, view_learner) | One tutor move per turn from the fixed list; code validates and runs it |
| Mastery | `src/tools/update.py`: one correct answer appends to `mastered_concepts` | `mastery_gate` only |
| Recall | Spacing fields in `src/schemas.py` unused | Need-driven recall, `SkillUseLog` logging |
| Personalising | `modality_preference` | Remove; use prior knowledge |
| Help | Not recorded | `TutorHelpLog` |
| Checks | None on learner code | Test runner + Jev method check |
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

1. Pushes for the answer before trying: no hint or fix (`try_first_gate`).
2. Right result, wrong method: not built alone.
2b. Milestone built with AI, she can't explain or change it: not built alone.
2c. Milestone built with AI, she explains it and makes a requested change: built alone.
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

Ordered by dependency. Each step is a story that goes through the repo's issue-to-PR flow (`CLAUDE.md`, `docs/SDLC.md`). Record every eval score and failure count in `docs/baseline.md` (Phase 1) and `docs/scores.md` (after).

Phase 1: foundations (one session)
1. Baseline: run current tests and evals; save scores to `docs/baseline.md`.
2. Data model (section 7) and course format. Coding course with the 2-milestone sample project (order-status tool, then refund tool), its tests and a reference solution. Stop for schema review.
3. Test runner (`TestResult`: passed/total + failures, several runs each) and Jev method check (flags `if "refund" in question:` routing).
4. Scripted-learner eval harness for section 11. Most evals fail until Phase 2. Record the failures.

Phase 2: the loop
5. Move contract and loop rewrite in `autonomous.py`: one validated tutor move per turn; `TutorMoveLog`.
6. `TutorHelpLog`, `try_first_gate`, `progress_gate`.
7. `walkthrough_check`, judge model, `built_alone_gate`.
8. Trace view and cost per session (`cost_usd`).
9. Same-session evals green: 1 to 5, 9, 10.

Phase 3: public-ready
10. Head-to-head benchmark vs plain Claude and plain GPT.
11. Split repos: public core, new private repo imports it. Nothing private exists before this step.

Phase 4: private product
12. Full course spine and context graph for course 1.
13. `SkillUseLog`, need-driven recall, max-gap fallback, `mastery_gate`. Simulated clock for multi-day evals. Evals 6 to 8 green.
14. Sign-in, rate limits, freemium caps; deploy from the private repo.
15. Later: company layer.

## 13. Production guardrails

- Rules live in code, never only in the prompt.
- Logic on the server; nothing sensitive reaches the browser.
- Sign-in and rate limits; per-user daily cap.
- Cost per session tracked from the first run.
