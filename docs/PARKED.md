# Parked until real users

**In plain words:** These are things we chose to skip while nobody uses the app yet. Each one is cheap to skip now and worth doing once real people depend on the site. When the first real users arrive, work down this list.

```
now (0 users):   speed first ──► ship straight to the site
later (users):   open this file ──► turn each item back on
```

How to use it:
- Parking something adds an entry here in the same PR: what, why it waits, where it's written down, and what "done" looks like.
- When you un-park an entry, delete it and link the PR that did it in the commit message.

| # | Parked | Why it can wait | Where it lives now |
|---|--------|-----------------|--------------------|
| P-1 | **Approve button before each deploy** | A bad deploy hurts nobody yet and rolls back in a minute | Closed PR #66 (final design `80c191c`); `.github/workflows/deploy.yml` header |
| P-2 | **Live agent evals before deploy** | They cost money per run | `.github/workflows/deploy.yml` header |
| P-3 | **Staging site** | One site can double as practice while nobody uses it | Discussed on #66 |
| P-4 | **Pre-launch tiering** (lowest tier, no "go up when unsure") | Speed matters more than process with no users | `CLAUDE.md` "Pre-launch mode", D-005 in `DESIGN_DECISIONS.md` |
| P-5 | **Codex P2 "S adds noticeable behaviour"** | Paused along with P-4 | `AGENTS.md` |
| P-6 | **tier-check status from a GitHub App** | Only the owner has write access, so nobody else can forge the status | Accepted risk on #59 |

## P-1 · Approve button before each deploy

Today `main` ships itself after CI passes (#72). Once there are users, add a pause where the owner clicks **Approve** before anything goes live.

- Reuse the design in PR #66, commit `80c191c`:
  - A `pick` job outside the gate chooses the newest green commit on `main` and shows it.
  - The `deploy` job behind the `production` environment ships exactly that commit.
  - It skips if a newer green commit exists, so it never rolls back.
- Move `FLY_API_TOKEN` from a repository secret to a `production` **environment** secret, with you as required reviewer.
- Fix the two Codex findings left open on `80c191c` first:
  - The deployment record shows the trigger SHA, not the shipped one.
  - A stale approval can evict a newer pending deploy.
- Done when: a merge to `main` waits for your Approve, and the shipped SHA matches the one shown.

## P-2 · Live agent evals before deploy

Run the paid eval suite on the commit about to ship, and stop the deploy if scores drop. Done when: a failing eval blocks the deploy.

## P-3 · Staging site

A second Fly app that updates on every merge with no approval. The live site stays behind P-1. About 15 lines in `deploy.yml`, plus a second app's cost. Done when: every merge is visible on staging before you approve live.

## P-4 · Pre-launch tiering

Turn "pace over process" off in `CLAUDE.md`. Pick the highest tier that fits and go up when unsure. Mark D-005 replaced in `DESIGN_DECISIONS.md`. Done when: `CLAUDE.md`, `docs/SDLC.md`, the playbook and the story template no longer mention pre-launch mode.

## P-5 · Codex P2 rule

Remove the "paused" note from the P2 rule in `AGENTS.md`, together with P-4. Done when: Codex flags an S PR that adds noticeable behaviour.

## P-6 · tier-check from a GitHub App

Anyone with write access can post a fake `tier-check` status. Do this before anyone other than the owner gets write access: post the status from a dedicated GitHub App and require that app as the status's source in branch protection. Done when: the ruleset only accepts `tier-check` from the app.

## P-7 · Sandbox for running learner code

Her code runs in a throwaway folder with no API keys, a timeout and no other isolation. Needs a real sandbox (no network, limited files and memory) before anyone else's code runs. Tracked in tech-debt #103. Done when: learner code runs in a sandbox with no network and no access to the host.

## P-8 · Prompt injection via code comments

Her code goes to Jev as text, so a comment like "answer no to everything" could sway the method check. Test this in the step 4 eval and harden if it shifts answers. Done when: the eval shows comments cannot flip a method answer.

## P-9 · Live Jev

The real Jev call needs `TYPESAFE_API_KEY` and `api.typesafe.ai` allowed through the network proxy. Tests stub it, so nothing here has run against the live service. Done when: one real `check_method` call returns answers in a cloud session.
