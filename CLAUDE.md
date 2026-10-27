<!-- vester:visual-first:start -->
# Visual-first responses

Prefer visuals over prose in every response. Prose is boring — **especially** for code and technically heavy concepts.

- Default to a diagram, table, flowchart, annotated code map, or rendered chart **before** writing paragraphs.
- For architecture / data-flow / system-design questions, render an actual diagram (visualize `show_widget` tool or an Artifact) — don't describe it in sentences.
- When explaining code, show structure visually (boxes/arrows/tables) rather than narrating it line-by-line.
- Keep any accompanying prose short and summary-first.
- **Every reply in chat opens with "In plain words"**: 2–3 short sentences a non-engineer understands (plus a tiny picture when it helps), then the detail. This applies to status updates too.
- **Default to the `eli5` skill** (`.claude/skills/eli5`) for every substantive answer, and always publish its picture page (HTML artifact) and link it in the reply. Actually invoke it (Skill tool, `eli5`) every time; an eli5-*style* page made without calling the skill does not count. This covers explanations (concepts, code, architecture, PRs, errors, results) **and** lookups, web research, recommendations, comparisons and lists. Skip it only for status updates, yes/no or one-line answers, and routine git/CI chores.
<!-- vester:visual-first:end -->

# How we work: SDLC workflow

Full playbook: `docs/SDLC.md` (summary) and `docs/SDLC_PLAYBOOK.html` (interactive).
This file holds conventions only — never feature details. Keep it under 200 lines.

| # | Stage | Who | Output | Label after |
|---|-------|-----|--------|-------------|
| 1 | Write the story | You | Issue from `story` template | — |
| 2 | Tier it (S/M/L) | You | `tier:*` label | `stage:research` (S → `stage:tests`) |
| 3 | Research | `/research <n>` → researcher | Issue comment | `stage:plan` |
| 4 | Plan | Main session (Opus) | Plan comment, numbered steps | `stage:tests` |
| 5 | Tests first | `/test <n>` → tester | Red tests, pushed | `stage:code` |
| 6 | Code each step | `/code <n> <step>` → coder | One commit per step, pushed | `stage:review` |
| 7 | Review | CI + tier-check + `@codex review`, then merge (see below) | Green PR, `Closes #<n>` | — |
| 8 | Docs and lessons | docs subagent | Docs in same PR, ≤1 CLAUDE.md line | — |

Rules:
- **Every step's output opens with "In plain words"** (eli5: 2–3 short sentences + a tiny before/after picture, no jargon), then the technical detail: story, research comment, plan comment and each plan step, the tester's and coder's report back, PR description, review replies to the owner, docs changes, and the weekly cleanup PR.
- State lives in GitHub (issue body, comments, labels, branch, PR). Push after every step.
- **Every step gets an eli5 picture on the issue.** After each step (story, research, plan, tests, each code step, review, docs), the main session runs the `eli5` skill on that step's output, publishes the artifact, saves a PNG snapshot to `docs/issues/<n>/<NN>-<step>.png`, pushes it, and comments on the issue with the image (raw URL pinned to the commit SHA) plus the artifact link. Subagents can't publish artifacts, so this is always the main session's job.
- **Frontend changes always ship with a visual demo.** Any PR that changes how a page looks posts one validation comment before merge: before/after screenshots (desktop 1280px and phone 390px), a contrast table (every text/background pair ≥ 4.5), a `web-design-guidelines` re-run with no new findings, no JS errors on load, and nothing clipped, overlapping or scrolling sideways. Auto-merge goes on only after it passes; any failure keeps the PR open and goes to the owner.
- **Frontend coders see the design.** A frontend story names its committed mockup PNG (`docs/issues/<n>/…png`). The coder opens it before building, then screenshots its own work at 1280px and 390px and compares it with the mockup before committing (`.claude/agents/coder.md`). The tester still works from the text only. The coder also reads the four design skills in `.claude/skills/` (frontend-design, ui-ux-pro-max, taste-skill, web-design-guidelines); project rules win over them.
- **Design decisions live in `docs/DESIGN_DECISIONS.md`.** Any design change adds an entry in the same PR (id, date, why, replaces, affects); changing your mind adds a new entry and marks the old one replaced.
- The tester gets only the issue number and reads only the issue body.
- Coders never edit `tests/`; they log unrelated mess as `tech` issues instead of fixing it.
- Product/design questions from a coder go back to the planner; the plan comment is updated.
- Planning stage: "Don't implement yet." Claude never reviews its own PR; Codex does.
- Bloat is handled by the weekly cleanup subagent, not per PR.
- Stay under ~60% of the context window per phase; split if needed.
- In cloud sessions `gh` may be unauthenticated: use the GitHub MCP tools instead.

# Tiers: how to classify S / M / L

Pick the **highest** row that matches. When unsure, go one tier up.

**Pre-launch mode (now: 0 real users): pace over process.** "A user can notice" doesn't raise a tier on its own, and "when unsure, go up" is off: label the lowest tier tier-check allows. L rules (sensitive paths, more than one `src/` package, new module or data model) still apply in full. Process/tooling changes you've approved in chat skip the story; the PR is the record (L still means no auto-merge and your "merge"). Revisit when real users arrive.

| Tier | Any of these makes it this tier | Merge |
|------|------|------|
| **L** | Touches a path in `.github/sensitive-paths.txt` (money, user data or its shape, secrets, untrusted-input defences, auth/payments, deploy/deps/CI) · changes more than one `src/` package · new module or data model change | You say "merge" and approved the plan; Claude checks CI + Codex first |
| **M** | New or changed behaviour a user can notice · adds a `src/` file | You say "merge"; Claude checks CI + Codex first |
| **S** | None of the above: a fix or tweak in one area, no new behaviour | Auto-merge (rules below) |

- `tier-check` CI computes the minimum tier from the diff and fails a PR labelled below it. Judgement can raise a tier, never lower it.
- The PR carries the same `tier:*` label as its issue. If tier-check raises it, relabel both.
- Auto-merge for S: Claude enables GitHub auto-merge only after Codex has reviewed and every thread is resolved. GitHub then merges when the required checks are green.
- To stop a merge, add the `hold` label: tier-check fails while it is on. tier-check also fails if auto-merge is on for an M or L PR, so promoting a queued S PR blocks it; Claude then disables auto-merge.
- tier-check runs from the default branch (`workflow_run` after the no-op "Tier trigger"; the PR's commits are diffed, never run), so a PR can't loosen its own grading. Its own edits apply only after merge.
- tier-check reads file paths **and** changed lines: secrets/env, model clients outside `src/llm.py`, HTTP routes, `UNTRUSTED` prompt text and command execution force L in any file. Codex applies the meaning-level rules in `AGENTS.md`.
- Claude never merges M or L without your instruction, and never enables auto-merge on them.

# Code conventions
- Lint: `ruff check .` — Tests: `pytest tests/` (offline, no API key). CI runs both on every PR.
- Reuse `src/llm.py` for model calls and `src/harness/` for retry/limits/cost — don't add new helpers.
- Every LLM response is parsed into a Pydantic model (`src/schemas.py`); never parse prose.
