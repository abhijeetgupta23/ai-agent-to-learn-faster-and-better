# Baseline (Phase 1, step 1)

## In plain words

This is the "before" photo of the repo. We record how the current agent scores, so every later change can be compared against these numbers. Any field marked "not run" has not been measured yet. It is left empty on purpose, not filled with a guess.

```
before: no record of where we started
after:  one table of today's numbers to compare every later step against
```

## Snapshot

| Field | Value |
|---|---|
| Commit | `df69fd3` |
| Date measured | 2026-11-18 |
| Python | 3.13 |
| Where | Claude Code cloud session, no `ANTHROPIC_API_KEY` set |

## Offline checks (measured 2026-11-18)

| Check | Result |
|---|---|
| `ruff check .` | Clean, 0 findings |
| `pytest tests/` | 182 passed, 0 failed, 12 skipped |

The 12 skips are all live red-team probes. They need a real API key:

| File | Skipped | Reason |
|---|---|---|
| `tests/test_redteam_ingestion.py` | 2 | live API key required for ingestion red-team |
| `tests/test_redteam_learner_input.py` | 10 | live API key required for red-team probes |

## Model-scored evals

These evals call the model and the judges, so they need an API key. Fresh runs are left empty until someone runs them with a key. The "last committed" rows are copied from results files already in the repo. Their run date isn't recorded in those files.

### `python run_evals.py`: 6 golden cases × 3 judges (pass = every judge ≥ 0.60)

| Case | gap_to_pedagogy | modality_fit | adaptive_progression | Pass |
|---|---|---|---|---|
| **Fresh run** | not run | not run | not run | not run |
| *Last committed (`evals/results.md`):* | | | | |
| case_01_novice_start | 0.70 | 1.00 | 1.00 | OK |
| case_02_struggling_use_socratic | 0.70 | 1.00 | 1.00 | OK |
| case_03_mastered_basics_practice | 0.95 | 1.00 | 1.00 | OK |
| case_04_step_down_overwhelmed | 1.00 | 1.00 | 1.00 | OK |
| case_05_interleave_confusables | 1.00 | 0.70 | 1.00 | OK |
| case_06_prereq_gap_blocks_advance | 1.00 | 1.00 | 1.00 | OK |
| **Overall (last committed)** | | | | 6/6, 0 failures |

### `python run_compare.py`: workflow vs autonomous, same 3 judges

| Field | Value |
|---|---|
| Fresh run | not run |
| Last committed | `evals/results_comparison.md` (system under test `claude-opus-4-8`, judges `claude-sonnet-4-6`) |

### Live red-team probes (12 tests above)

| Field | Value |
|---|---|
| Fresh run | not run |

## Section 11 evals (scripted learners)

Not built yet. Step 4 adds them and records which ones fail here.

| # | Eval | Result |
|---|---|---|
| 1 | Pushes for the answer before trying | not built |
| 2 | Right result, wrong method | not built |
| 2b | Built with AI, can't explain or change it | not built |
| 2c | Built with AI, explains and changes it | not built |
| 3 | Hint given, then a passing solution | not built |
| 4 | Brand-new idea, no prior knowledge | not built |
| 5 | Already knows the idea | not built |
| 6 | Same-session reuse | not built |
| 7 | Unaided use 5 days later | not built |
| 8 | Must-know concept near the max gap | not built |
| 9 | Prompt-leak attempt | not built |
| 10 | Off-topic chatbot use | not built |

## To fill the empty rows

With `ANTHROPIC_API_KEY` set:

```
python run_evals.py
python run_compare.py
pytest tests/test_redteam_ingestion.py tests/test_redteam_learner_input.py
```

Copy the scores into the "Fresh run" rows above, with the date.
