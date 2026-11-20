# Glossary

**In plain words:** One name for each thing in Learn Faster. Python classes are CamelCase; names that are stored or shown (fields, logs, file keys) are snake_case. If an older doc uses the old name, this page wins.

```
before: concept, piece, course pack, ownership check, MoveLog ...
after:  skill,   milestone, course,   walkthrough check, TutorMoveLog ...
```

Code: `src/schemas.py` (the records), `src/course.py` (the loader).

| New name | What it is (one line) | Replaces |
|---|---|---|
| `course` / `Course` | One subject's project: skills, milestones, tests, method questions, judge rubric, walkthrough questions. | course pack |
| `milestone` / `Milestone` | One piece of the project, built in one sitting; has a task, tests and a reference solution. | piece |
| `Skill` | Something the learner must be able to do. | `Concept` |
| `needs` | The skill ids a skill builds on. | `builds_on` |
| `WalkthroughCheck` | She explains, changes or fixes a line of her own code; records pass or fail. | `OwnershipCheck` |
| `walkthrough_questions` | The course's prompts for the walkthrough, by kind: `explain`, `change`, `fix`. | ownership-check prompts |
| `TestResult` | Passed / total plus failures for one submission (from `check_submission`). | `CheckRun` |
| `MethodQuestion` | A yes/no question about her code that a milestone asks Jev (id, question, `wrong_answer`, optional `yes_means` / `no_means`). Replaces red-flag rules. | `red_flag_rules` |
| method check / `check_method` | `LoadedCourse.check_method` sends the milestone's method questions to Jev (one call, code never run) and returns a `JudgeReview`. | red-flag scan |
| `JudgeIssue` | One method question answered the wrong way: `question_id` and `probability` of the wrong answer. | `RedFlag` |
| Jev | The calibrated yes/no judge (`src.llm.ask_jev`) that gives P(yes) for each method question. Failures raise `JevError`. | |
| `check_submission` | `LoadedCourse.check_submission` runs the milestone's tests on her code, several runs, in a throwaway folder; returns a `TestResult`. | |
| `JudgeReview` | The separate model's verdict on method: `method_ok`, notes, model name. | `JudgeVerdict` |
| `judge_rubric` | The course's criteria the judge uses. | judge rubric (loose) |
| tutor move / `TutorMove` | One action the model picks per turn from the fixed list of 11. | move |
| `TutorMoveLog` | One row per move: move, skill, gate, allowed, reason, tokens, `cost_usd`. | `MoveLog` |
| `cost_usd` | Cost of a move in US dollars. | `cost` |
| `TutorHelpLog` | One row per help given (`explain`, `example`, `hint`, `fix`). | `HelpLedger` |
| `SkillUseLog` | One row per use of a skill: gap in days, help used, unaided. | `ConceptUse` |
| `MasteryLog` | One row per mastery decision (`confirmed`). | `MasteryEvent` |
| `Submission.content` | What she handed in. | `artifact` |
| `Submission.content_type` | Kind of content; only `code` for now. | `artifact_type` |
| `try_first_gate` | No `hint` or `fix` before she has tried. | gate 1 |
| `built_alone_gate` | `built_alone` only with no help, all tests passing, method OK and walkthrough passed. | gate 2 |
| `progress_gate` | Progress is shown before a session closes. | gate 3 |
| `mastery_gate` | `confirm_mastery` only after an unaided use after a real gap, in a later session. | gate 4 |

## What the code does today

- `TestResult.failures` is a list of `TestFailure` (test id, first line of the message).
- Every `ts` on the new records must carry a timezone and is stored in UTC; a time with no timezone is rejected.
- `method_questions` are asked of Jev by `check_method`; a question is an issue when P(wrong answer) >= threshold (default 0.5).
- The four gate names are valid values for `TutorMoveLog.gate`. The gates themselves are not built yet.
- `Submission.content_type` accepts only `code`.
- All records reject unknown fields.
