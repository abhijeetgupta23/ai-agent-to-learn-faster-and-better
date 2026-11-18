# Handoff to Claude Code: Learn Faster rebuild

Put these in the repo's `docs/` folder:
- `learn-faster-agent-architecture.md` (the brief; build order is section 12)
- `learn-faster-product.md` (context only)
- this file

## Ground rules

- One phase per session. Start each in plan mode and wait for approval before changing files.
- Commit after every step in section 12.
- Ask before anything destructive (deleting files, rewriting history, changing deploys).
- Nothing from Phase 4 goes in the public repo, ever. Graph data and course spines start in the private repo after step 11.
- Record every eval score and failure count: `docs/baseline.md` in Phase 1, then `docs/scores.md` with a date per run. These numbers are needed later.
- Don't invent numbers. Leave a field empty if it hasn't been measured.

## Session 1 prompt (Phase 1: foundations)

```
Read docs/learn-faster-agent-architecture.md and CLAUDE.md.
Do Phase 1 from section 12 (steps 1 to 4) in this session, committing
after each step.

1. Baseline: run the current tests and evals. Save every score and
   failure count to docs/baseline.md.
2. Data model (section 7) and course-pack format ("Course packs" in
   section 1). Add a coding pack with the 2-piece sample project
   (order-status tool, then refund tool), its tests and a reference
   solution. STOP and show me the schema before continuing.
3. Check runner (runs a submission against the pack's tests, several
   runs each, returns passed/total plus failures) and static read
   (flags `if "refund" in question:` routing).
4. Scripted-learner eval harness for the evals in section 11. Wire the
   pass conditions. Most will fail until Phase 2; record which fail in
   docs/baseline.md.

Don't touch the agent loop yet. Use plan mode first.
```

## Next sessions

- Session 2, Phase 2 (steps 5 to 9): "Do Phase 2 from section 12. Use the Phase 1 evals as the tests. Update docs/scores.md after each step."
- Session 3, Phase 3 (steps 10 and 11): "Do Phase 3. Propose the repo split before moving any files."
- Session 4 onward, Phase 4: one step per session.

## Open decisions to settle in session 2

From section 10 of the architecture doc: live chat or submission-based sessions; which models for the tutor, checks and judge.
