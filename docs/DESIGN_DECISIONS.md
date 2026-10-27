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
- date: 2026-10-27 · status: active · source: owner (#68)
- replaces: the always-visible "Your name" box on the first screen
- affects: `#user` (hidden until "change" is clicked), "Learning as alice · change" line
- why: a first-time visitor shouldn't fill in a form before seeing value. The value still defaults to `alice` and replays still set it.

## D-009 · Home is left-aligned with a list, not centred with tiles
- date: 2026-10-27 · status: active · source: owner (#68, skill check)
- replaces: centred headline and a grid of identical subject chips
- affects: home intro and `#domain-chips`, drawn concept map beside them
- why: the taste-skill and frontend-design rules ban a centred default headline and rows of identical cards. A left-aligned question, a plain two-column list and one drawn map (the single bold thing) follow them.
