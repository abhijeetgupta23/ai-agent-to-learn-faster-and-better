"""
Bounded retries for external calls (Anthropic API; any future HTTP fetch).

Why this exists: the agent's only external dependency at runtime is the
Anthropic API, and API calls fail in two distinct ways that deserve distinct
handling:

  - *Transient* failures (timeouts, connection resets, 429 rate limits,
    5xx server errors) usually succeed on a retry. We retry these — at most
    twice, with linear backoff (1s, then 2s). Anything more aggressive risks
    amplifying an outage; anything less leaves easy wins on the table.
  - *Permanent* failures (401 bad key, 400 malformed request, schema
    validation bugs) will fail identically on every retry. Retrying these
    only adds latency and cost, so we don't.

Either way, callers never see a raw SDK exception. Exhausted or permanent
failures are wrapped in `ExternalCallError`, which carries enough structure
(label, attempts, transient flag, cause) for the agent loop to end the
session gracefully and for the server to return a meaningful status code.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

import anthropic
import httpx

R = TypeVar("R")

# Linear backoff per the failure-handling policy: first retry after 1s,
# second after 2s. Length of this tuple == max retries.
BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0)


class ExternalCallError(Exception):
    """
    A failed external call, after retries were exhausted or judged pointless.

    Structured so the loop and server can act on it without string-parsing:
    `transient=True` means "the world was flaky" (retried, still failing);
    `transient=False` means "this request can never succeed as-is".
    """

    def __init__(self, label: str, attempts: int, transient: bool, cause: Exception):
        self.label = label
        self.attempts = attempts
        self.transient = transient
        self.cause = cause
        kind = "transient (retries exhausted)" if transient else "permanent (not retried)"
        super().__init__(
            f"External call '{label}' failed after {attempts} attempt(s) — "
            f"{kind}: {type(cause).__name__}: {cause}"
        )

    def to_payload(self) -> dict:
        """Shape for SSE error events / JSON responses."""
        return {
            "error": "external_call_failed",
            "label": self.label,
            "attempts": self.attempts,
            "transient": self.transient,
            "cause": f"{type(self.cause).__name__}: {self.cause}",
        }


def is_transient(exc: Exception) -> bool:
    """
    Classify an exception as worth retrying.

    Transient: network-level failures, timeouts, 429 rate limits, 5xx server
    errors. Permanent: everything else — notably 4xx client errors (bad key,
    bad request) and local bugs (ValueError, ValidationError), which would
    fail identically on retry.
    """
    # Anthropic SDK: connection errors (including timeouts) have no status.
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    # Status-bearing SDK errors: retry rate limits and server-side failures.
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    # Raw httpx (future URL fetches go through this same wrapper).
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    # Stdlib networking.
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    # OpenAI-compatible SDK (DeepSeek experiments) — optional dependency, so
    # classify only when it's importable.
    try:
        import openai
    except ImportError:
        return False
    if isinstance(exc, openai.APIConnectionError):
        return True
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def call_with_retries(
    fn: Callable[[], R],
    *,
    label: str,
    backoff: tuple[float, ...] = BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> R:
    """
    Call `fn`, retrying transient failures per the backoff schedule.

    `label` names the call for the structured error (e.g. "llm:plan").
    `sleep` is injectable so tests don't actually wait.

    Raises ExternalCallError — never a raw SDK/network exception.
    """
    attempts = 0
    while True:
        attempts += 1
        try:
            return fn()
        except ExternalCallError:
            raise  # already wrapped by a nested call; don't double-wrap
        except Exception as exc:
            if not is_transient(exc):
                raise ExternalCallError(label, attempts, transient=False, cause=exc) from exc
            retry_index = attempts - 1  # 0 after first failure
            if retry_index >= len(backoff):
                raise ExternalCallError(label, attempts, transient=True, cause=exc) from exc
            sleep(backoff[retry_index])
