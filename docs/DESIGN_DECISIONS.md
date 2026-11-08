# Design decisions

**In plain words:** One place for every design choice: what we decided, why, and when. If we change our mind, we add a new entry and mark the old one as replaced, so the history stays readable.

```
D-001 ──► D-004 (replaces)        each entry: id · date · status · replaces · affects · why
```

How to use it:
- Any change to how the app looks or how design work is run adds an entry here, in the same PR.
- Never edit an old entry's decision. Add a new one, and set the old one's `status: replaced by D-NNN`.
- `affects` names what the decision touches (a CSS variable, a screen, a process), so it can be turned into a graph later if needed.

---

## D-001 · One look for every subject, no per-subject themes
- date: 2026-10-20 · status: active · source: owner (#65)
- replaces: per-subject themes (default, terminal, editorial, warm)
- affects: `docs/visual/index.html` palette, `TOPIC_THEME` (removed)
- why: four outfits made the app feel inconsistent, and the main one was the generic purple of AI-made apps.

## D-002 · Board + paper
- date: 2026-10-20 · status: active · source: owner (#65)
- replaces: —
- affects: `--board` (header, tutor's brain), `--bg` / `--paper` (page, lessons)
- why: chalkboard green gives the classroom identity; lessons sit on light paper because dark-on-light text is read more accurately (Piepenbrock, Mayr & Buchner). The green is the brand, not a learning claim: evidence that a specific hue helps learning is weak.

## D-003 · Chalk yellow only for highlights
- date: 2026-10-20 · status: active · source: owner (#65)
- replaces: —
- affects: `--chalk` (primary button, current step, the learner's gap, highlighted phrases)
- why: pointing at the essential part helps memory when used sparingly (signaling meta-analyses: Schneider et al. 2018, Richter et al. 2016). Large yellow areas would dilute it.

## D-004 · Cool paper, not warm cream
- date: 2026-10-20 · status: active · source: owner (#65)
- replaces: warm cream `--bg: #f3eee0` (first paint in `25fa5ef`)
- affects: `--bg`, `--paper`, `--border`, `--tint`
- why: warm cream is one of the common looks of AI-made pages (frontend-design skill). A cool, slightly green-grey paper (`#f3f5f2`) matches the board.

## D-005 · Pre-launch: visible UI changes ship as S with a visual demo
- date: 2026-10-20 · status: active · source: owner (#63, #65)
- replaces: "a user can notice it → M"
- affects: SDLC tiering (`CLAUDE.md`), every frontend PR
- why: with no real users yet, speed matters more than process. To make up for skipping the owner's "merge", every frontend PR posts a visual demo (before/after screenshots at desktop and phone width, contrast table, guidelines re-run, no JS errors) before auto-merge. Revisit when real users arrive.

## D-006 · Self-host the fonts, no Google Fonts
- date: 2026-10-20 · status: active · source: owner (#65, Codex P1 on #67)
- replaces: loading Fraunces and Source Sans 3 from `fonts.googleapis.com`
- affects: `docs/visual/fonts/` (woff2 + OFL licence), `@font-face` rules in `docs/visual/index.html`
- why: loading from Google made every visitor's browser contact a new outside service (their IP address and the page they're on). Same look, no third-party call.

## D-007 · Home has one primary action; replays are secondary
- date: 2026-10-27 · status: active · source: owner (#68)
- replaces: three big featured cards above the start button
- affects: home screen in `docs/visual/index.html` (Start button, "Watch a replay" rows, tutor's brain hidden until a session starts)
- why: five things competing for the first click slow a first-time visitor down. One yellow button, with replays as quiet text rows below it (Pro Max `primary-action`, `progressive-disclosure`). The "Orchestration: autonomous agent" note was removed from home: it is developer talk, and the Eval page covers how the tutor works.

## D-008 · The name is asked later, not up front
- date: 2026-10-27 · status: replaced by D-010 · source: owner (#68)
- replaces: the always-visible "Your name" box on the first screen
- affects: `#user` (hidden until "change" is clicked), "Learning as alice · change" line
- why: a first-time visitor shouldn't fill in a form before seeing value. The value still defaults to `alice` and replays still set it.

## D-009 · Home is left-aligned with a list, not centred with tiles
- date: 2026-10-27 · status: active · source: owner (#68, skill check)
- replaces: centred headline and a grid of identical subject chips
- affects: home intro and `#domain-chips`, drawn concept map beside them
- why: the taste-skill and frontend-design rules ban a centred default headline and rows of identical cards. A left-aligned question, a plain two-column list and one drawn map (the single bold thing) follow them.

## D-010 · No name on screen until there's auth; the learner id is a hidden default
- date: 2026-10-27 · status: active · source: owner (#68)
- replaces: D-008 (name behind a "change" link)
- affects: `#user` (now a hidden input, value `alice`), removed "Learning as alice · change" line
- why: accounts come later, once this is a product. Until then a name box is a form with no purpose. The request still sends the same default id, so the server sees no change.

## D-011 · The board is the page
- date: 2026-11-01 · status: active · source: owner (#73)
- replaces: D-009's board-as-one-map-beside-a-list layout
- affects: home in `docs/visual/index.html` (full-width board hero, big footer repeating the name)
- why: the chalkboard is the product's one bold idea, so the hero is the board itself with the subject list and the map with the gap circled. The footer repeats the name, very large, to close the page the same way.

## D-012 · "Why this lesson" is always visible; the tutor's internals sit behind a closed disclosure
- date: 2026-11-01 · status: active · source: owner (#73)
- replaces: the always-open "Tutor's brain" panel beside the lesson
- affects: lesson screen (`#split`, board column, `<details>` "See how the tutor decided" holding `#flowchart`, `#thinking`, `#trace`)
- why: a learner needs the reason in plain words, not function names. The full trace is still one click away (progressive disclosure).

## D-013 · Square flat buttons; no arrows, resting shadows, gradients, thin rules, eyebrows or badges
- date: 2026-11-01 · status: active · source: owner (#73, skills installed in #70)
- replaces: rounded and shadowed controls, pill tags, 1px dividers
- affects: every control and surface in `docs/visual/index.html`
- why: taste-skill and frontend-design name these as template chrome. Surfaces are separated by a step in tone (`--paper-2`), and the one chalk button marks the main action.

## D-014 · The home shows proof; the 6/6 badge is gone
- date: 2026-11-01 · status: active · source: owner (#73)
- replaces: the `6/6` badge in the header
- affects: "Watch it teach Alice" (replay excerpt) and "Every lesson choice is checked" (results table from `/evals`)
- why: a badge asks the visitor to trust a number. A replay excerpt and a per-case table let them see the evidence.

## D-015 · The free-topic box is deferred to its own story
- date: 2026-11-01 · status: active · source: owner (#73)
- replaces: the typed-topic box in the first mock
- affects: none (not built)
- why: it needs a server route that takes untrusted input, which is tier L.

## D-016 · The pitch lives on the board, not on a cover page
- date: 2026-11-08 · status: active · source: owner (#75)
- replaces: the idea of a separate cover page before the home
- affects: home hero in `docs/visual/index.html` (3-step strip under "No account needed.")
- why: the board already holds the promise and the gap map, so a short strip of three drawn steps (pick a subject, we find your gap, lessons adjust) answers "what happens after Start" without an extra click. No buttons, no numbers, icons decorative.
