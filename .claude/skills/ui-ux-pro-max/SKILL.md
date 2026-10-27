---
name: ui-ux-pro-max
description: "UI/UX rules for designing, building, reviewing or fixing interfaces: accessibility, touch targets, layout, typography, colour, motion, forms, navigation and charts. Rules-only install: read references/quick-reference.md and references/pro-rules.md."
---

<!-- Adapted from nextlevelbuilder/ui-ux-pro-max-skill (MIT, commit 28b3b8d). Change: rules-only.
     The upstream skill also ships a Python search script and ~3 MB of style/palette data; those are
     not installed here, so there is nothing to run. The two reference files are copied unchanged. -->

# UI/UX Pro Max (rules only)

Use this when a task changes how something **looks, feels, moves, or is interacted with**: new pages, UI components, colour/type/spacing/layout choices, UX or accessibility reviews, navigation, animation, responsive behaviour. Skip it for backend, API, data or infrastructure work.

## Rule categories by priority

Work through them in order. Full rule text with rationale is in `references/quick-reference.md` (read on demand). App polish rules and the pre-delivery checklist are in `references/pro-rules.md`.

| Priority | Category | Impact | Key checks (must have) | Anti-patterns (avoid) |
|----------|----------|--------|------------------------|------------------------|
| 1 | Accessibility | CRITICAL | Contrast 4.5:1, alt text, keyboard nav, aria-labels | Removing focus rings, icon-only buttons without labels |
| 2 | Touch & Interaction | CRITICAL | Min size 44×44px, 8px+ spacing, loading feedback | Hover-only affordances, instant state changes (0ms) |
| 3 | Performance | HIGH | WebP/AVIF, lazy loading, reserve space (CLS < 0.1) | Layout thrashing, layout shift |
| 4 | Style Selection | HIGH | Match product type, consistency, SVG icons (no emoji) | Mixing flat and skeuomorphic, emoji as icons |
| 5 | Layout & Responsive | HIGH | Mobile-first breakpoints, viewport meta, no horizontal scroll | Horizontal scroll, fixed px containers, disabled zoom |
| 6 | Typography & Color | MEDIUM | Base 16px, line-height 1.5, semantic colour tokens | Text < 12px, grey-on-grey, raw hex in components |
| 7 | Animation | MEDIUM | Context-aware timing, motion conveys meaning | One duration everywhere, animating width/height, no reduced-motion |
| 8 | Forms & Feedback | MEDIUM | Visible labels, error near field, helper text, progressive disclosure | Placeholder-only labels, errors only at top, overwhelm upfront |
| 9 | Navigation Patterns | HIGH | Predictable back, bottom nav ≤5, deep linking | Overloaded nav, broken back, no deep links |
| 10 | Charts & Data | LOW | Legends, tooltips, accessible colours | Colour as the only signal |

The references sometimes mention a `search.py` script, `--domain` / `--design-system` queries or `data/*.csv` files: those are **not installed**; use the rule text itself.

Rule ids in the references (e.g. `primary-action`, `progressive-disclosure`) can be quoted in stories and reviews.

## In this repo

Project rules win over this skill: no Google Fonts or other third-party font/CDN requests (fonts are self-hosted), one look (see `docs/DESIGN_DECISIONS.md`), and every frontend change ships with a visual demo (`CLAUDE.md`).
