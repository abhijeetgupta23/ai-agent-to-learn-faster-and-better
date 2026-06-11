"""
Deployment guards for the public demo: access gate, rate limit, budget caps.

These are *hosting hygiene*, not agent logic — they exist so a single API key
behind a public URL can't be drained by a stranger. All config is env-driven
so the same image runs locally (guards effectively off) or on Railway (guards
on) with no code change. Everything here is in-memory or a small JSON file;
nothing hosting-specific.

  - DemoTokenMiddleware — if DEMO_TOKEN is set, session endpoints require a
    matching `X-Demo-Token` header (or `?token=`); /health and /visual stay
    open. No token configured ⇒ open (local dev).
  - RateLimiter — crude per-IP cap on session creation (in-memory sliding
    window).
  - Budget config — per-session and daily-global USD caps, read from env and
    enforced by the endpoints via src/harness/cost.py.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# --- config (env-driven) ---------------------------------------------------

DEMO_TOKEN = os.environ.get("DEMO_TOKEN", "").strip()

# Per-session cost cap (USD). A session that crosses this terminates gracefully.
PER_SESSION_USD_CAP = float(os.environ.get("DEMO_SESSION_USD_CAP", "1.00"))
# Daily global spend cap (USD). When crossed, session endpoints return a
# "budget exhausted for today" response until the UTC date rolls over.
DAILY_USD_CAP = float(os.environ.get("DEMO_DAILY_USD_CAP", "20.00"))

# Per-IP session-creation rate limit.
RATE_LIMIT_PER_HOUR = int(os.environ.get("DEMO_RATE_LIMIT_PER_HOUR", "5"))

# Endpoints that must stay reachable without a token (and skip budget checks).
_OPEN_PREFIXES = ("/health", "/visual", "/docs", "/openapi.json", "/redoc")
_OPEN_EXACT = ("/",)


def _is_open_path(path: str) -> bool:
    return path in _OPEN_EXACT or any(path.startswith(p) for p in _OPEN_PREFIXES)


class DemoTokenMiddleware(BaseHTTPMiddleware):
    """Require X-Demo-Token on protected endpoints when DEMO_TOKEN is set."""

    async def dispatch(self, request: Request, call_next):
        if not DEMO_TOKEN or _is_open_path(request.url.path):
            return await call_next(request)
        supplied = request.headers.get("x-demo-token") or request.query_params.get("token")
        if supplied != DEMO_TOKEN:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "unauthorized",
                    "message": (
                        "This is a gated demo. Provide a valid demo token via the "
                        "'X-Demo-Token' header to start a session."
                    ),
                },
            )
        return await call_next(request)


class RateLimiter:
    """In-memory sliding-window limiter, keyed by client IP."""

    def __init__(self, max_per_hour: int = RATE_LIMIT_PER_HOUR):
        self.max_per_hour = max_per_hour
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, client_ip: str) -> bool:
        """Record a hit; return True if allowed, False if over the limit."""
        now = time.time()
        window = self._hits[client_ip]
        while window and now - window[0] > 3600:
            window.popleft()
        if len(window) >= self.max_per_hour:
            return False
        window.append(now)
        return True


def client_ip(request: Request) -> str:
    # Honour the first X-Forwarded-For hop (Railway/most PaaS sit behind a proxy).
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def daily_budget_exhausted() -> bool:
    from src.harness import cost

    return cost.DAILY.today_usd() >= DAILY_USD_CAP


def budget_exhausted_response() -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "error": "demo_budget_exhausted",
            "message": (
                "The demo's budget for today is used up. Please come back "
                "tomorrow — the daily allowance resets at 00:00 UTC."
            ),
        },
    )


def rate_limited_response() -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limited",
            "message": (
                f"Too many sessions from your address. The demo allows "
                f"{RATE_LIMIT_PER_HOUR} new sessions per hour — try again later."
            ),
        },
    )
