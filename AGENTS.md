# AGENTS.md

Read by Codex when it reviews pull requests. Project conventions live in `CLAUDE.md`;
the tier rules in `CLAUDE.md` ("Tiers: how to classify S / M / L") apply here too.

## Review guidelines

Every PR carries one `tier:S`, `tier:M` or `tier:L` label. `tier-check` CI sets a
minimum from file paths and simple line patterns. Your job is the part those rules
can't see: what the change *means*. Never suggest lowering a tier.

Flag as **P1** if the PR is labelled below L and the change does any of these, even
in a file not listed in `.github/sensitive-paths.txt`:

- Touches money: spend caps, cost accounting, rate limits, pricing, billing or payments.
- Reads, stores or changes the shape of user or learner data (memory store, schemas, migrations).
- Reads a secret or credential, or sends data to a new external service.
- Calls a model without going through `src/llm.py` and the `src/harness/` cost meter.
- Weakens a prompt-injection defence: the "UNTRUSTED" prompt text, or the red-team tests in `tests/test_redteam_*.py`.
- Adds an HTTP route, or bypasses the demo token or rate limiter in `src/server/guards.py`.
- Touches auth, sessions or permissions.

Also flag as **P1**, whatever the label:

- Any change under `.github/` (workflows, `scripts/check_tier.py`, `sensitive-paths.txt`). These grade every other PR. A workflow that writes a commit status named `tier-check` is a forged gate.
- A test that calls a real LLM API, or a test deleted or loosened so a failing change can pass.
- Code that parses free-text model output instead of a Pydantic model from `src/schemas.py`.

Flag as **P2** if a PR labelled S adds behaviour a user can notice. That makes it at least M.
