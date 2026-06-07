# Cost analysis

_All per-operation costs are computed from real token counts captured in `docs/traces/*.json` — actual LLM calls, not estimates. Pricing is Anthropic list price for **claude-opus-4-8** ($5.00 / 1M input, $25.00 / 1M output). Adaptive thinking is ON, which is included in the output tokens below._

## Per-operation cost (measured)

| Operation | avg input tok | avg output tok | cost/call |
|---|--:|--:|--:|
| `diagnose` | 3,630 | 335 | $0.0265 |
| `plan` | 4,296 | 966 | $0.0456 |
| `generate:reading` | 592 | 830 | $0.0237 |
| `judge:gap_to_pedagogy` | 1,598 | 556 | $0.0219 |
| `judge:modality_fit` | 1,020 | 336 | $0.0135 |
| `judge:adaptive_progression` | 972 | 263 | $0.0114 |
| `extract_graph` (one-time/domain) | 3,647 | 3,728 | $0.1114 |

## Cost of one teaching session

A session = 1 diagnose + 1 plan + 4 generated artifacts (one per workflow step):

- **$0.167 per session** (10,295 input + 4,622 output tokens)
- The graph extraction ($0.111) is **paid once per domain**, then cached and reused across every learner — so it is **not** part of per-session cost after the first learner.

## Cost of one eval run

An eval case = diagnose + plan + 1 generate + 3 judges:

- **$0.143 per case**
- **$0.86 for the full 6-case suite**

The judges roughly double the cost of a case vs. a bare session — they are the price of *proving* the output is correct. You run them in CI / on changes, not per learner.

## Scale projection

_Projected from the measured per-session cost, assuming graph caching (extract-once-per-domain) is in effect._

| Scenario | Sessions | Cost |
|---|--:|--:|
| 1 learner-sessions | 1 | $0.17 |
| 100 learner-sessions | 100 | $16.70 |
| 1,000 learner-sessions | 1,000 | $167.03 |
| 10,000 learner-sessions | 10,000 | $1,670.31 |
| 100,000 learner-sessions | 100,000 | $16,703.12 |

Plus a flat ~$0.11 per unique domain ingested (one-time).

## Optimization levers (projected)

**1. Prompt-cache the learning graph.** The graph (~3,704 input tokens) is re-sent on every diagnose/plan/judge call within a session. Caching it (cache reads cost ~0.1x) saves roughly **$0.017/session** on the repeated sends — ~10% of session cost. The graph is a stable prefix, so this is a clean win. *(Not yet implemented; the `MemoryStore` already isolates the graph as the cacheable unit.)*

**2. Run judges on a cheaper model.** The three judges cost $0.047/case on Opus. On Haiku 4.5 ($1/$5) they'd cost $0.009/case — a **80% cut** on the eval half of the bill. Judges apply tight rubrics with deterministic signals pre-computed, so a smaller model is defensible here; keep diagnose/plan on Opus where the reasoning matters.

**3. Generate artifacts on Sonnet.** Artifact generation is bulk text, not hard reasoning: $0.0237/artifact on Opus vs. $0.0142 on Sonnet 4.6 — and generate runs N times per session, so this scales. Diagnose/plan (the actual decisions) stay on Opus.

**4. Lower `effort` / disable thinking for generate.** Generation doesn't need deliberation — the trace already shows adaptive thinking skipping reasoning on `generate:reading` calls. Explicitly setting `effort: low` or thinking off for generate trims output tokens with no quality loss.

## Combined projection at 10k sessions/month

| Configuration | $/session | $/10k sessions |
|---|--:|--:|
| All-Opus, no caching (today) | $0.167 | $1,670 |
| + graph cache + Sonnet generate | $0.112 | $1,124 |

Roughly a **33% reduction** on learner-facing cost, before touching diagnose/plan quality.

## Honest caveats

- Numbers reflect adaptive thinking ON (the default), which adds output tokens — it's what makes the agent's reasoning auditable. Turning it off is cheaper but reverts to a black box.
- Sample size is small (the captured traces). Treat per-call costs as ±20%; the *structure* (graph caching + tiered models is the big lever) holds regardless.
- List pricing; volume/commitment discounts and batch API (50% off, for non-interactive eval runs) are not modeled.
