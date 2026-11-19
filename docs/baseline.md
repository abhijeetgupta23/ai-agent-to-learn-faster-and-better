# Baseline scores

### In plain words

This page is the "before" snapshot: what the checks and evals said before Phase 1 changes anything. Later scores go in `docs/scores.md` so we can compare against these. A row that says "not run" means we could not run it, and says why.

Measured on 2026-11-19 at commit f0a9bd8 (base 0438cd8 plus the story #87 tests commit).

| Command | Date | Commit | Result |
|---|---|---|---|
| `pytest tests/` | 2026-11-19 | f0a9bd8 | 190 passed, 0 failed, 12 skipped, 0 errors (with this page in place; the 8 checks in `tests/test_baseline_doc.py` errored 8 errors before it existed, other tests: 182 passed) |
| `ruff check .` | 2026-11-19 | f0a9bd8 | 0 findings (All checks passed!) |
| `python run_evals.py` | 2026-11-19 | f0a9bd8 | not run: needs ANTHROPIC_API_KEY, none in this environment (failed with "Could not resolve authentication method") |
| `python run_compare.py` | 2026-11-19 | f0a9bd8 | not run: needs ANTHROPIC_API_KEY, none in this environment (failed with "Could not resolve authentication method") |

## Where later scores go

- After Phase 1, new scores go in `docs/scores.md`, each with a date and commit. Never invent a number.
- Phase 1 step 4 eval failures: add them below this line when found.

### Eval failures (Phase 1 step 4)

_None recorded yet._
