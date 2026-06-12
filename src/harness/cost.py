"""
Runtime cost accounting.

The offline `scripts/cost_analysis.py` reports cost from captured traces; this
module is the *live* counterpart — it accumulates real spend as calls happen,
so the server can enforce budget caps (per-session and per-day).

One entry point, `record(model, usage)`, is called once per LLM response from
`src/llm.py`. It fans the cost out to:
  - any active per-request `CostMeter`s (a contextvar stack), used for the
    per-session cap, and
  - a persistent `DailySpend` counter, used for the global daily cap. The
    counter is JSON on disk so a process restart doesn't reset the day's
    spend (a demo on a small host restarts often).

Pricing is Anthropic list pricing, $/1M tokens. (The offline cost script keeps
its own copy of this table; kept in sync by hand — small and rarely changes.)
"""

from __future__ import annotations

import contextvars
import json
import os
import threading
from contextlib import contextmanager
from datetime import date
from pathlib import Path

# $/1M tokens. Cache reads are billed at 10% of input (Anthropic prompt caching).
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-8": {"in": 5.00, "out": 25.00},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
    "claude-haiku-4-5": {"in": 1.00, "out": 5.00},
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00},
}
# Fall back to Opus pricing for an unknown model id — never under-count spend.
_FALLBACK = PRICING["claude-opus-4-8"]


def usd_for(usage: dict, model: str) -> float:
    p = PRICING.get(model, _FALLBACK)
    inp = usage.get("input_tokens", 0)
    out = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    return (inp / 1e6) * p["in"] + (out / 1e6) * p["out"] + (cache_read / 1e6) * p["in"] * 0.10


class CostMeter:
    """A running total for one logical scope (e.g. one HTTP request/session)."""

    def __init__(self) -> None:
        self.total_usd = 0.0
        self.n_calls = 0

    def add(self, usd: float) -> None:
        self.total_usd += usd
        self.n_calls += 1


_active_meters: contextvars.ContextVar[tuple[CostMeter, ...]] = contextvars.ContextVar(
    "active_cost_meters", default=()
)


@contextmanager
def meter():
    """Accumulate the cost of LLM calls made inside this block."""
    m = CostMeter()
    token = _active_meters.set(_active_meters.get() + (m,))
    try:
        yield m
    finally:
        _active_meters.reset(token)


class DailySpend:
    """
    Persistent per-day spend counter. Resets when the UTC date rolls over.

    Backed by a small JSON file so restarts on the host don't zero the day's
    spend mid-demo. Thread-safe for the single-process server.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> tuple[str, float]:
        if self.path.exists():
            try:
                d = json.loads(self.path.read_text())
                return d["date"], float(d["usd"])
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
        return date.today().isoformat(), 0.0

    def _today_usd_unlocked(self) -> float:
        day, usd = self._load()
        return usd if day == date.today().isoformat() else 0.0

    def today_usd(self) -> float:
        with self._lock:
            return self._today_usd_unlocked()

    def add(self, usd: float) -> None:
        with self._lock:
            current = self._today_usd_unlocked()
            self.path.write_text(
                json.dumps({"date": date.today().isoformat(), "usd": current + usd})
            )


def _default_daily_path() -> Path:
    root = os.environ.get("ADAPTIVE_LEARNING_STORE_DIR", "./data/store")
    return Path(root) / "daily_spend.json"


# Process-wide daily counter. Lazily resolvable so tests can point it elsewhere.
DAILY = DailySpend(_default_daily_path())


def record(model: str, usage: dict) -> float:
    """
    Account for one LLM call. Called once per response from src/llm.py.

    Returns the call's cost so callers can log it if they wish.
    """
    usd = usd_for(usage, model)
    for m in _active_meters.get():
        m.add(usd)
    DAILY.add(usd)
    return usd
