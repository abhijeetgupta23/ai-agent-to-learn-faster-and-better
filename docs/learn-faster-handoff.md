# Learn Faster rebuild: session handoff

**In plain words:** This page tells each new Claude Code session which part of the rebuild to do next. The goals come from the architecture brief. The way of working comes from this repo's normal flow: every step starts as an issue and ends as a PR.

```
before: paste prompt → plan mode → commit per step
after:  pick next step → story issue → tier → research → plan → tests → code → PR
```

Brief: `docs/learn-faster-agent-architecture.md` (build order: §12, open decisions: §10, evals: §11).
Process: `CLAUDE.md` and `docs/SDLC.md`. If this page and those disagree, they win.

## Ground rules

- Each build-order step in §12 is one story: issue from the `story` template, tier, then `/research`, plan, `/test`, `/code`, PR. No ad-hoc commits.
- Big steps can be split into several stories. Keep each phase under ~60% of the context window.
- Record every eval score and failure count with a date: `docs/baseline.md` in Phase 1, then `docs/scores.md`. Leave a field empty if it hasn't been measured. Never invent a number.
- Nothing from Phase 4 goes in this public repo, ever. Graph data and course spines start in the private repo after step 11.
- Ask before anything destructive (deleting files, rewriting history, changing deploys).

## Expected tiers

tier-check decides the real tier from the diff. This is a forecast, so L stories are planned for your approval up front.

| Step | What | Likely tier | Why |
|---|---|---|---|
| 1 | Baseline scores | S | Docs only |
| 2 | Data model + course-pack format | L | Data model change, `src/schemas.py` |
| 3 | Check runner + static read | L | New module; runs learner code |
| 4 | Scripted-learner eval harness | L | New module |
| 5–8 | Loop rewrite, gates, judge, trace | L | Changes control flow, model calls, data shape |
| 9 | Same-session evals green | M or L | Depends on what the fixes touch |
| 10 | Head-to-head benchmark | L | New model clients |
| 11 | Repo split | L | Moves packages, deploy |

## Session prompts

### Session 1: Phase 1 (steps 1 to 4)

```
Read docs/learn-faster-agent-architecture.md and docs/learn-faster-handoff.md.
Phase 1 is steps 1 to 4 of §12. Open one story issue per step (story template),
tier each, and take step 1 through the full flow to a PR.

Step notes:
1. Baseline: run current tests and evals; save every score and failure count
   to docs/baseline.md. If an eval needs an API key we don't have, record it
   as "not run" with the reason.
2. Data model (§7) and course-pack format (§1 "Course packs"). Coding pack with
   the 2-piece sample project (order-status tool, then refund tool), its tests
   and a reference solution. The plan comment must show the full schema; I
   approve it before /test.
3. Check runner (passed/total + failures, several runs each) and static read
   (flags `if "refund" in question:` routing).
4. Scripted-learner eval harness for §11 with pass conditions wired. Most fail
   until Phase 2; record which in docs/baseline.md.

Don't touch the agent loop yet.
```

### Session 2: Phase 2 (steps 5 to 9)

```
Phase 2 of §12, as stories. Use the Phase 1 evals as the tests. Update
docs/scores.md after each PR. Settle §10 decisions 2 and 3 in the first
plan comment.
```

### Session 3: Phase 3 (steps 10 and 11)

```
Phase 3 of §12, as stories. Propose the repo split in the plan comment before
moving any files.
```

### Session 4 onward: Phase 4

One step per session, in the private repo.

## Open decisions to settle in session 2

From §10 of the brief:
- Live chat or submission-based sessions.
- Which models for the tutor, checks and judge (cheaper ones for checks and judge).
