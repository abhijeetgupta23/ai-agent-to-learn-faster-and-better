# SDLC workflow

One long-lived planner keeps the big picture; every other job is a subagent that
starts with a clean context and hands off through GitHub, not chat.
Interactive version: [`SDLC_PLAYBOOK.html`](SDLC_PLAYBOOK.html).

```mermaid
flowchart TD
  S1[1. Write the story<br/>you · issue] --> S2[2. Tier it<br/>S / M / L]
  S2 --> S3[3. Research<br/>researcher · issue comment]
  S3 --> S4[4. Plan<br/>main · Opus · plan comment]
  S4 --> S5[5. Tests first<br/>tester · issue body only]
  S5 --> S6[6. Code each step<br/>coder · one per step]
  S6 --> S7[7. Review<br/>CI + Codex · you merge]
  S7 --> S8[8. Docs and lessons<br/>docs subagent]
  S2 -. tier S .-> S5
  S6 -. questions .-> S4
  S7 -. fixes .-> S6
  W[W. Weekly cleanup<br/>cleanup subagent · whole repo]
```

## Tiers

| Tier | Looks like | Stages |
|------|-----------|--------|
| S | Small fix in one area, no new behaviour | 5, 6, 7 |
| M | New behaviour inside one module | All |
| L | Cross-cutting, new module, or data model change | All + you approve the plan before tests |

## Where state lives

| State | Lives in |
|-------|----------|
| Spec | Issue body (`story` template) |
| Research | Issue comment |
| Plan | Issue comment |
| Current stage | Issue label `stage:*` |
| Tests and code | Branch commits, pushed after every step |
| Review | PR comments |
| Tech debt | Issues labelled `tech` |
| Lessons | CLAUDE.md |

## Files

| Path | Role |
|------|------|
| `.claude/agents/researcher.md` | Read-only code map → issue comment |
| `.claude/agents/tester.md` | Red tests from the issue body, edits `tests/` only |
| `.claude/agents/coder.md` | One plan step, never edits `tests/` |
| `.claude/agents/docs.md` | Docs from `git diff main...HEAD` |
| `.claude/agents/cleanup.md` | Weekly bloat removal, no behaviour change |
| `.claude/commands/{research,test,code}.md` | `/research <n>`, `/test <n>`, `/code <n> <step>` |
| `.github/ISSUE_TEMPLATE/story.yml` | Story shape: who, action, outcome, criteria, tier |
| `.github/workflows/ci.yml` | ruff + pytest — make it a required check |

## Weekly cleanup

```bash
git switch -c cleanup/$(date +%G-w%V)
ruff check . --select F401,F841,ERA001 --fix
vulture src/ --min-confidence 80
npx jscpd src/
# then: "Use the cleanup subagent on the findings and open tech issues."
pytest tests/
```

## One-time setup (manual)

- Labels: `stage:research`, `stage:plan`, `stage:tests`, `stage:code`, `stage:review`,
  `tier:S`, `tier:M`, `tier:L`, `story`, `tech`, `cleanup`
  (`for l in research plan tests code review; do gh label create "stage:$l"; done`).
- Branch protection on `main`: require the CI `test` checks to pass.
- Enable the Codex GitHub reviewer for `@codex review`.
