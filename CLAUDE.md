# Project
Learn Faster: a personal AI tutor that teaches a work skill by having you build a real project, one piece a day. For now, for people who already code.
Build brief: `docs/learn-faster-agent-architecture.md` (build order: §12). Next step per session: `docs/learn-faster-handoff.md`.
- The model decides: that's where personalisation and flexibility come from. Code guarantees: rules live in gates, never only in the prompt.
- Every build-order step runs through the issue-to-PR flow below (story → … → PR), never as ad-hoc commits, even if a pasted handoff or prompt says "plan mode, commit per step".
- Log every eval score with a date (`docs/baseline.md`, then `docs/scores.md`). Never invent a number.
- This repo is public: no graph data, course spines, tuned values or learner data.

<!-- vester:visual-first:start -->
# Visual-first responses

Prefer visuals over prose in every response. Prose is boring — **especially** for code and technically heavy concepts.

- Default to a diagram, table, flowchart, annotated code map, or rendered chart **before** writing paragraphs.
- For architecture / data-flow / system-design questions, render an actual diagram (visualize `show_widget` tool or an Artifact) — don't describe it in sentences.
- When explaining code, show structure visually (boxes/arrows/tables) rather than narrating it line-by-line.
- Keep any accompanying prose short and summary-first.
- **Every reply in chat opens with "In plain words"**: 2–3 short sentences a non-engineer understands (plus a tiny picture when it helps), then the detail. This applies to status updates too.
- **Default to the `anthropic-skills:explain-tech` skill** (`/anthropic-skills:explain-tech`) for every substantive answer, and always publish its page (HTML artifact) and link it in the reply. Actually invoke it (Skill tool, `anthropic-skills:explain-tech`) every time; a page in its style made without calling the skill does not count. Use `/eli5` only when the owner asks for it. This covers explanations (concepts, code, architecture, PRs, errors, results) **and** lookups, web research, recommendations, comparisons and lists. Skip it only for status updates, yes/no or one-line answers, and routine git/CI chores.
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
- **Every step's output opens with "In plain words"** (2–3 short sentences + a tiny before/after picture, no jargon), then the technical detail: story, research comment, plan comment and each plan step, the tester's and coder's report back, PR description, review replies to the owner, docs changes, and the weekly cleanup PR.
- State lives in GitHub (issue body, comments, labels, branch, PR). Push after every step.
- **One explain-tech page per story, not per step.** When the story's PR is opened, the main session runs the `anthropic-skills:explain-tech` skill on what the whole story changed (before/after), publishes the artifact, saves a PNG to `docs/issues/<n>/picture.png`, pushes it, and comments on the issue with the image (raw URL pinned to the commit SHA) plus the artifact link. For frontend stories, the visual demo's screenshots go in it. Steps in between post text only ("In plain words" first). Subagents can't publish artifacts, so this is always the main session's job.
- **Frontend changes always ship with a visual demo.** Any PR that changes how a page looks posts one validation comment before merge: before/after screenshots (desktop 1280px and phone 390px), a contrast table (every text/background pair ≥ 4.5), a `web-design-guidelines` re-run with no new findings, no JS errors on load, and nothing clipped, overlapping or scrolling sideways. Auto-merge goes on only after it passes; any failure keeps the PR open and goes to the owner.
- **Frontend coders see the design.** A frontend story names its committed mockup PNG (`docs/issues/<n>/…png`). The coder opens it before building, then screenshots its own work at 1280px and 390px and compares it with the mockup before committing (`.claude/agents/coder.md`). The tester still works from the text only. The coder also reads the four design skills in `.claude/skills/` (frontend-design, ui-ux-pro-max, taste-skill, web-design-guidelines); project rules win over them.
- **Design decisions live in `docs/DESIGN_DECISIONS.md`.** Any design change adds an entry in the same PR (id, date, why, replaces, affects); changing your mind adds a new entry and marks the old one replaced.
- The tester gets only the issue number and reads only the issue body.
- Coders never edit `tests/`; they log unrelated mess as `tech-debt` issues instead of fixing it.
- Product/design questions from a coder go back to the planner; the plan comment is updated.
- Planning stage: "Don't implement yet." Claude never reviews its own PR; Codex does.
- After opening a PR, Claude subscribes to its activity without asking and acts whenever something needs it: answers Codex, fixes CI, and turns on auto-merge for S once every thread is resolved, or merges directly if checks are already green.
- Bloat is handled by the weekly cleanup subagent, not per PR.
- **Suggest a post when work fits the owner's brand.** After a PR merges something on the owner's two content pillars (production agents; evals and feedback loops), end the reply with one suggested LinkedIn post. Find the owner's artifacts "B2B brand strategy, explained" and "LinkedIn post playbook, explained" with the Artifact tool (`action: list`), read both, then draft it: hook under 140 characters, Problem → Root cause → Fix → Result, a one-line lesson, one expert question, no link. Measured numbers only, and pass every playbook check (no employer IP, no teaching-method internals). Suggest only; the owner posts.
- Anything deliberately put off until there are real users goes in `docs/PARKED.md`, so it isn't forgotten at launch. Add the entry in the same PR that parks it.
- Stay under ~60% of the context window per phase; split if needed.
- In cloud sessions `gh` may be unauthenticated: use the GitHub MCP tools instead.

# Tiers: S / M / L
Full rules and how tier-check works: `docs/SDLC.md` § Tiers.

**Pre-launch mode (0 real users):** label the lowest tier tier-check allows; the L rules still apply in full. Process changes you approve in chat skip the story; the PR is the record. Revisit when real users arrive.

| Tier | Any of these | Merge |
|------|------|------|
| **L** | Path in `.github/sensitive-paths.txt` · 2+ `src/` packages · new module or data model | Your "merge" + approved plan |
| **M** | New behaviour a user can notice · new `src/` file | Your "merge" |
| **S** | None of the above | Claude, once Codex is clear (rule above) |

- tier-check sets the minimum tier from the diff and fails a PR labelled below it. Judgement can raise a tier, never lower it; relabel the issue and PR together.
- The `hold` label stops any merge. Claude never merges M or L, or turns on auto-merge for them, without your "merge".

# Code conventions
- Lint: `ruff check .` — Tests: `pytest tests/` (offline, no API key). CI runs both on every PR.
- Reuse `src/llm.py` for model calls and `src/harness/` for retry/limits/cost — don't add new helpers.
- Every LLM response is parsed into a Pydantic model (`src/schemas.py`); never parse prose.
