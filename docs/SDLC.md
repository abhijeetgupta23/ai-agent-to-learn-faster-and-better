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

| Tier | Any of these makes it this tier | Stages | Merge |
|------|-----------|--------|-------|
| L | Touches `.github/sensitive-paths.txt` · more than one `src/` package · new module or data model change | All + you approve the plan before tests | On your instruction, after Claude checks CI + Codex |
| M | New behaviour a user can notice · new `src/` file · over 150 changed lines | All | On your instruction, after Claude checks CI + Codex |
| S | None of the above | 5, 6, 7 | Auto-merge once Codex threads are resolved and checks are green |

```mermaid
flowchart TD
  D[PR diff] --> Q1{Sensitive path?<br/>2+ src packages?}
  Q1 -- yes --> L[min tier L]
  Q1 -- no --> Q2{New src file?<br/>over 150 lines?}
  Q2 -- yes --> M[min tier M]
  Q2 -- no --> S[min tier S]
  L & M & S --> C{label below min?}
  C -- yes --> F[tier-check fails]
  C -- no --> P[tier-check passes]
```

The check (`.github/workflows/tier.yml` → `.github/scripts/check_tier.py`) sets a
floor from the diff. It also scans the changed lines of non-test
Python: reading env vars or secrets, a model client outside `src/llm.py`, a new
HTTP route, `UNTRUSTED` prompt text, or running commands all force L, whatever the
file. The grading workflow (`tier.yml`) runs from the default branch via
`workflow_run`, triggered by the no-op `tier-trigger.yml`, and the PR's commits
are only diffed, never run, so a PR cannot loosen its own grading. Edits to the workflow, checker or rules take
effect only after they merge. It also fails while a PR has the `hold` label,
or while auto-merge is on for an M or L PR. Behaviour changes it cannot see are judgement: the planner
raises the tier, never lowers it.

### Who picks the tier, in plain words

Think of the tier as a size sticker on every change. Two helpers pick it, and
one rule keeps them honest.

```
              L ┃  money, user data, secrets, deploy, 2+ src/ packages
              M ┃  new src/ file, >150 lines, or new behaviour
- - - - - - - - ┃ - - - - tier-check's line: nothing goes below it - -
              S ┃  small fix in one area
```

| Helper | What it looks at | Uses AI? | What it can do |
|---|---|---|---|
| tier-check (`check_tier.py`) | Which files changed, how many lines, and risky patterns in the changed lines | No. Plain rules: same change, same answer | Draws the line: the lowest tier allowed |
| Codex, following `AGENTS.md` | What the change means (money, data, secrets, auth, injection defences) | Yes | Flags a too-low label as P1, never lowers it |
| The researcher agent, then you | The story: does it change what users see? | Yes, the agent suggests; you set the label | Push the tier **up**, never below the line |

- tier-check can't see intent, so it can't tell a risky one-line change from a
  harmless one. That's why people and the AI helper can raise the tier.
- The AI helper can be wrong, so it can't lower the tier. If it suggests too
  low a tier, tier-check fails the PR.
- tier-check and its rules come from `main`, never from the PR being graded,
  so a change can't rewrite the rules that grade it.

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
| `.github/workflows/tier-trigger.yml`, `tier.yml` | No-op trigger on PR events → trusted grader on the default branch, posts the `tier-check` status |
| `.github/scripts/check_tier.py`, `.github/sensitive-paths.txt` | The tier rules: sensitive paths, size, spread and changed-line patterns |
| `AGENTS.md` | Codex review guidelines: meaning-level tier and safety rules |

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
  `tier:S`, `tier:M`, `tier:L`, `story`, `tech`, `cleanup`, `hold` (blocks any merge while applied)
  (`for l in research plan tests code review; do gh label create "stage:$l"; done`).
- Branch protection on `main`: require the `test (py3.10/3.11/3.12)` checks and the
  `tier-check` status, and "Require conversation resolution before merging" (so Codex
  threads block). `tier-check` first appears once `tier.yml` is on `main`.
- Settings → General → "Allow auto-merge" (needed for tier S).
- Enable the Codex GitHub reviewer for `@codex review`.
