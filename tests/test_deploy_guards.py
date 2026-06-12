"""
Offline tests for the Phase 7 deployment guards (src/server/guards.py,
src/harness/cost.py). No API key, no network.
"""

from __future__ import annotations

from src.harness import cost
from src.server.guards import RateLimiter


# --- cost accounting -------------------------------------------------------

def test_usd_for_uses_pricing_and_cache_discount():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 0}
    # Opus: $5 in + $25 out per 1M.
    assert abs(cost.usd_for(usage, "claude-opus-4-8") - 30.0) < 1e-9
    # Cache reads billed at 10% of input rate.
    cached = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 1_000_000}
    assert abs(cost.usd_for(cached, "claude-opus-4-8") - 0.5) < 1e-9


def test_unknown_model_falls_back_to_opus_pricing():
    usage = {"input_tokens": 1_000_000, "output_tokens": 0}
    assert cost.usd_for(usage, "some-future-model") == cost.usd_for(usage, "claude-opus-4-8")


def test_meter_accumulates_and_record_fans_out(tmp_path, monkeypatch):
    # Point the daily counter at a temp file.
    monkeypatch.setattr(cost, "DAILY", cost.DailySpend(tmp_path / "daily.json"))
    with cost.meter() as m:
        cost.record("claude-haiku-4-5", {"input_tokens": 1_000_000, "output_tokens": 0})  # $1.00
        cost.record("claude-haiku-4-5", {"input_tokens": 1_000_000, "output_tokens": 0})  # $1.00
    assert abs(m.total_usd - 2.0) < 1e-9
    assert m.n_calls == 2
    assert abs(cost.DAILY.today_usd() - 2.0) < 1e-9


def test_daily_spend_persists_across_instances(tmp_path):
    path = tmp_path / "daily.json"
    a = cost.DailySpend(path)
    a.add(3.5)
    # A fresh instance (simulating a process restart) reads the same day's total.
    b = cost.DailySpend(path)
    assert abs(b.today_usd() - 3.5) < 1e-9


def test_daily_spend_resets_on_date_change(tmp_path, monkeypatch):
    import src.harness.cost as cost_mod

    path = tmp_path / "daily.json"
    path.write_text('{"date": "2000-01-01", "usd": 99.0}')
    d = cost_mod.DailySpend(path)
    # Stale date ⇒ counts as 0 today.
    assert d.today_usd() == 0.0


# --- rate limiting ---------------------------------------------------------

def test_rate_limiter_allows_then_blocks():
    rl = RateLimiter(max_per_hour=3)
    assert rl.check("1.2.3.4")
    assert rl.check("1.2.3.4")
    assert rl.check("1.2.3.4")
    assert not rl.check("1.2.3.4")  # 4th within the hour is blocked
    # A different IP has its own budget.
    assert rl.check("5.6.7.8")


def test_rate_limiter_window_expiry(monkeypatch):
    import src.server.guards as guards_mod

    t = {"now": 1000.0}
    monkeypatch.setattr(guards_mod.time, "time", lambda: t["now"])
    rl = RateLimiter(max_per_hour=1)
    assert rl.check("9.9.9.9")
    assert not rl.check("9.9.9.9")
    t["now"] += 3601  # an hour and change later
    assert rl.check("9.9.9.9")  # window has slid; allowed again
