<!-- vester:visual-first:start -->
# Visual-first responses

Prefer visuals over prose in every response. Prose is boring — **especially** for code and technically heavy concepts.

- Default to a diagram, table, flowchart, annotated code map, or rendered chart **before** writing paragraphs.
- For architecture / data-flow / system-design questions, render an actual diagram (visualize `show_widget` tool or an Artifact) — don't describe it in sentences.
- When explaining code, show structure visually (boxes/arrows/tables) rather than narrating it line-by-line.
- Keep any accompanying prose short and summary-first.
- **Default to the `eli5` skill** (`.claude/skills/eli5`) for any explanation: concepts, code, architecture, PRs, errors, results. Skip it only for status updates, one-line answers, and routine git/CI chores.
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
| 7 | Review | CI + `@codex review`, you merge | Green PR, `Closes #<n>` | — |
| 8 | Docs and lessons | docs subagent | Docs in same PR, ≤1 CLAUDE.md line | — |

Rules:
- State lives in GitHub (issue body, comments, labels, branch, PR). Push after every step.
- The tester gets only the issue number and reads only the issue body.
- Coders never edit `tests/`; they log unrelated mess as `tech` issues instead of fixing it.
- Product/design questions from a coder go back to the planner; the plan comment is updated.
- Planning stage: "Don't implement yet." Claude never reviews or merges its own PR.
- Bloat is handled by the weekly cleanup subagent, not per PR.
- Stay under ~60% of the context window per phase; split if needed.
- In cloud sessions `gh` may be unauthenticated: use the GitHub MCP tools instead.

# Code conventions
- Lint: `ruff check .` — Tests: `pytest tests/` (offline, no API key). CI runs both on every PR.
- Reuse `src/llm.py` for model calls and `src/harness/` for retry/limits/cost — don't add new helpers.
- Every LLM response is parsed into a Pydantic model (`src/schemas.py`); never parse prose.
